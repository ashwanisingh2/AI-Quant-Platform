"""Kotak Neo broker adapter — offline tests with a fake SDK client (no network, no orders).

Run: python -m unittest scripts.test_kotak_broker
"""
import importlib.util
import logging
import re
import unittest

from apps.engine.brokers import available_brokers, get_broker
from apps.engine.brokers.kotak_broker import (
    SEBI_OPS_LIMIT,
    KotakBroker,
    KotakSessionExpired,
    OrderRateGuard,
    OrderRateLimitExceeded,
    _marketable_limit,
    new_order_tag,
    redact_sdk_logs,
)


class FakeNeo:
    """neo_api_client.NeoAPI ka minimal stand-in. Sirf wahi methods jo adapter use karta hai."""

    def __init__(self, ltp=100.0):
        self.ltp = ltp
        self.calls = []
        self.place_response = {"stat": "Ok", "stCode": 200, "nOrdNo": "250122000612876"}
        self.ip = "203.0.113.10"
        self.order_rows = []
        self.position_rows = []

    def _log(self, name, **kw):
        self.calls.append((name, kw))

    def totp_login(self, mobile_number=None, ucc=None, totp=None):
        self._log("totp_login", mobile_number=mobile_number, ucc=ucc, totp=totp)
        return {"data": {"status": "success", "token": "SECRET-VIEW-TOKEN"}}

    def totp_validate(self, mpin=None):
        self._log("totp_validate", mpin=mpin)
        return {"data": {"status": "success", "token": "SECRET-TRADE-TOKEN"}}

    def logout(self):
        self._log("logout")
        return {"stat": "Ok"}

    def whatsmyip(self):
        self._log("whatsmyip")
        return {"data": [{"ip": self.ip}], "status": "success"}

    def limits(self, **kw):
        self._log("limits")
        return {"stat": "Ok", "stCode": 200, "Net": "19.41"}

    def positions(self):
        self._log("positions")
        return {"stat": "ok", "stCode": 200, "data": self.position_rows}

    def order_report(self, order_id=None):
        self._log("order_report")
        return {"stat": "Ok", "stCode": 200, "data": self.order_rows}

    def search_scrip(self, exchange_segment="", symbol="", **kw):
        self._log("search_scrip", exchange_segment=exchange_segment, symbol=symbol)
        return [{"pTrdSymbol": f"{symbol}-EQ", "pSymbol": str(abs(hash(symbol)) % 90000 + 10000)},
                {"pTrdSymbol": f"{symbol}-BE", "pSymbol": "1"}]

    def quotes(self, instrument_tokens=None, quote_type=None):
        self._log("quotes", instrument_tokens=instrument_tokens, quote_type=quote_type)
        return {"stat": "Ok", "data": [{"ltp": str(self.ltp)}]}

    def place_order(self, **kw):
        self._log("place_order", **kw)
        return self.place_response

    def cancel_order(self, order_id=None, amo="NO", isVerify=False):
        self._log("cancel_order", order_id=order_id)
        return {"stat": "Ok", "stCode": 200}

    def placed(self):
        return [kw for name, kw in self.calls if name == "place_order"]


def live_broker(client=None, **kw):
    params = dict(consumer_key="ck", mobile="+919999999999", ucc="UCC1", mpin="123456",
                  totp="654321", dry_run=False, client=client or FakeNeo())
    params.update(kw)
    return KotakBroker(**params)


class DryRunTests(unittest.TestCase):
    def test_dry_run_needs_no_credentials_or_sdk(self):
        broker = get_broker("kotak", dry_run=True)
        self.assertEqual(broker.connect()["mode"], "dry_run")
        self.assertIn("dry_run", broker.mode)

    def test_dry_run_fill_is_simulated_and_updates_positions(self):
        broker = get_broker("kotak", dry_run=True)
        broker.set_price(250.0)
        order = broker.place_market_order("NSE", "RELIANCE", "BUY", 10, product="CNC")
        self.assertEqual(order["status"], "COMPLETE")
        self.assertEqual(order["order_type"], "LIMIT")
        self.assertEqual(broker.positions()[0]["qty"], 10)

    def test_registry_lists_kotak_with_required_env(self):
        entry = next(b for b in available_brokers() if b["name"] == "kotak")
        self.assertEqual(set(entry["required_env"]),
                         {"KOTAK_CONSUMER_KEY", "KOTAK_MOBILE", "KOTAK_UCC", "KOTAK_MPIN"})


class LiveConstructionTests(unittest.TestCase):
    def test_missing_creds_fail_before_sdk_import(self):
        with self.assertRaises(ValueError) as ctx:
            KotakBroker(dry_run=False, consumer_key=None, mobile=None, ucc="U", mpin=None)
        self.assertIn("KOTAK_CONSUMER_KEY", str(ctx.exception))
        self.assertNotIn("ck-", str(ctx.exception))

    def test_connect_without_totp_refuses_and_sends_nothing(self):
        fake = FakeNeo()
        broker = live_broker(fake, totp=None)
        with self.assertRaises(ValueError):
            broker.connect()
        self.assertEqual(fake.calls, [])

    def test_totp_is_one_time_use(self):
        fake = FakeNeo()
        broker = live_broker(fake)
        broker.connect()
        self.assertIsNone(broker._totp)
        with self.assertRaises(ValueError):
            broker.connect()  # dusri baar TOTP nahi hai

    def test_order_refused_before_login(self):
        broker = live_broker()
        with self.assertRaises(RuntimeError):
            broker.positions()


class LiveOrderTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNeo(ltp=100.0)
        self.broker = live_broker(self.fake)
        self.broker.connect()

    def test_connect_sequence_and_static_ip_ok(self):
        names = [n for n, _ in self.fake.calls]
        self.assertEqual(names[:3], ["totp_login", "totp_validate", "whatsmyip"])

    def test_static_ip_mismatch_refuses_and_logs_out(self):
        fake = FakeNeo()
        fake.ip = "198.51.100.7"
        broker = live_broker(fake, static_ip="203.0.113.10")
        with self.assertRaises(ValueError):
            broker.connect()
        self.assertIn("logout", [n for n, _ in fake.calls])
        self.assertFalse(broker._logged_in)

    def test_buy_is_limit_order_not_market(self):
        self.broker.place_market_order("NSE", "RELIANCE", "BUY", 5, product="CNC")
        sent = self.fake.placed()[-1]
        self.assertEqual(sent["order_type"], "L")
        self.assertNotEqual(sent["order_type"], "MKT")
        self.assertEqual(sent["exchange_segment"], "nse_cm")
        self.assertEqual(sent["product"], "CNC")
        self.assertEqual(sent["validity"], "DAY")
        self.assertEqual(sent["transaction_type"], "B")
        self.assertEqual(sent["trading_symbol"], "RELIANCE-EQ")
        self.assertEqual(sent["quantity"], "5")
        self.assertEqual(sent["price"], "100.50")  # 100 * 1.005 → tick 0.05 par ceil

    def test_sell_limit_rounds_down_below_ltp(self):
        self.broker.place_market_order("NSE", "RELIANCE", "SELL", 5, product="MIS")
        sent = self.fake.placed()[-1]
        self.assertEqual(sent["price"], "99.50")
        self.assertEqual(sent["transaction_type"], "S")
        self.assertEqual(sent["product"], "MIS")

    def test_order_number_returned_as_open(self):
        order = self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertEqual(order["order_id"], "250122000612876")
        self.assertEqual(order["status"], "OPEN")

    def test_sdk_error_response_raises_without_leaking_payload(self):
        self.fake.place_response = {"error": "SECRET-TRADE-TOKEN leaked in message"}
        with self.assertRaises(RuntimeError) as ctx:
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_missing_order_number_is_not_reported_as_success(self):
        self.fake.place_response = {"stat": "Ok", "stCode": 200}
        with self.assertRaises(RuntimeError):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)

    def test_fno_and_unsupported_exchange_rejected(self):
        with self.assertRaises(ValueError):
            self.broker.place_market_order("NSE", "NIFTY-23OCT25-FUT", "BUY", 1)
        with self.assertRaises(ValueError):
            self.broker.place_market_order("NFO", "RELIANCE", "BUY", 1)

    def test_zero_or_bad_side_rejected_before_sending(self):
        with self.assertRaises(ValueError):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 0)
        with self.assertRaises(ValueError):
            self.broker.place_market_order("NSE", "RELIANCE", "HOLD", 1)
        self.assertEqual(self.fake.placed(), [])

    def test_cancel_is_requested_not_confirmed(self):
        self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        result = self.broker.cancel_order("250122000612876")
        self.assertEqual(result["status"], "CANCEL_REQUESTED")


class SymbolAndPriceTests(unittest.TestCase):
    def test_trading_symbol_mapping(self):
        self.assertEqual(KotakBroker._trading_symbol("RELIANCE"), "RELIANCE-EQ")
        self.assertEqual(KotakBroker._trading_symbol("BAJAJ-AUTO"), "BAJAJ-AUTO-EQ")
        self.assertEqual(KotakBroker._trading_symbol("RELIANCE-BE"), "RELIANCE-BE")

    def test_marketable_limit_is_tick_aligned_and_directional(self):
        self.assertEqual(_marketable_limit(100.0, "BUY", 0.005), 100.5)
        self.assertEqual(_marketable_limit(100.0, "SELL", 0.005), 99.5)
        ticks = _marketable_limit(333.33, "BUY", 0.005) * 20
        self.assertEqual(round(ticks, 6), round(ticks))

    def test_status_mapping_unknown_states_are_flagged(self):
        b = KotakBroker(dry_run=True)
        self.assertEqual(b._to_local_order({"ordSt": "complete", "trnsTp": "B"})["status"], "COMPLETE")
        self.assertEqual(b._to_local_order({"ordSt": "open", "trnsTp": "S"})["status"], "OPEN")
        self.assertEqual(b._to_local_order({"ordSt": "something new"})["status"], "UNKNOWN")


class PortfolioTests(unittest.TestCase):
    def test_net_qty_and_avg_price_follow_documented_formula(self):
        fake = FakeNeo()
        fake.position_rows = [{
            "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "lotSz": "1", "multiplier": "1",
            "genNum": "1", "genDen": "1", "prcNum": "1", "prcDen": "1",
            "cfBuyQty": 0, "flBuyQty": 10, "cfSellQty": 0, "flSellQty": 4,
            "cfBuyAmt": 0, "buyAmt": 100.0, "cfSellAmt": 0, "sellAmt": 0,
        }, {  # zero net → skip
            "trdSym": "TCS-EQ", "exSeg": "nse_cm", "cfBuyQty": 1, "flSellQty": 1,
        }]
        broker = live_broker(fake)
        broker.connect()
        positions = broker.positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["qty"], 6)
        self.assertEqual(positions[0]["avg_price"], 10.0)

    def test_available_cash_from_limits_net(self):
        broker = live_broker()
        broker.connect()
        self.assertEqual(broker.margins()["available_cash"], 19.41)


class OrderRateGuardTests(unittest.TestCase):
    def test_ten_per_second_allowed_eleventh_blocked(self):
        guard = OrderRateGuard(clock=lambda: 100.0)
        for _ in range(SEBI_OPS_LIMIT):
            guard.acquire("NSE")
        with self.assertRaises(OrderRateLimitExceeded):
            guard.acquire("NSE")

    def test_window_slides_after_one_second(self):
        now = [100.0]
        guard = OrderRateGuard(clock=lambda: now[0])
        for _ in range(SEBI_OPS_LIMIT):
            guard.acquire("NSE")
        now[0] = 101.0
        guard.acquire("NSE")  # purana window khatam

    def test_limit_is_per_exchange(self):
        guard = OrderRateGuard(max_per_second=1, clock=lambda: 5.0)
        guard.acquire("NSE")
        guard.acquire("BSE")
        with self.assertRaises(OrderRateLimitExceeded):
            guard.acquire("NSE")

    def test_invalid_limit_rejected(self):
        for bad in (0, 11):
            with self.assertRaises(ValueError):
                OrderRateGuard(max_per_second=bad)


class LiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNeo(ltp=100.0)
        self.broker = live_broker(self.fake)
        self.broker.connect()

    def test_eleventh_order_in_a_second_is_never_sent(self):
        self.broker._rate = OrderRateGuard(clock=lambda: 50.0)
        for _ in range(SEBI_OPS_LIMIT):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        with self.assertRaises(OrderRateLimitExceeded):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertEqual(len(self.fake.placed()), SEBI_OPS_LIMIT)

    def test_cancel_counts_toward_ops_limit(self):
        self.broker._rate = OrderRateGuard(max_per_second=1, clock=lambda: 50.0)
        self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        with self.assertRaises(OrderRateLimitExceeded):
            self.broker.cancel_order("250122000612876")
        self.assertNotIn("cancel_order", [n for n, _ in self.fake.calls])

    def test_explicit_broker_reject_is_rejected_not_unknown(self):
        self.fake.place_response = {"stat": "Not_Ok", "stCode": 1003, "emsg": "insufficient funds"}
        order = self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertEqual(order["status"], "REJECTED")
        self.assertEqual(order["order_id"], "")
        self.assertEqual(order["reason_code"], 1003)

    def test_session_expired_raises_specific_error(self):
        self.fake.place_response = {"stat": "Not_Ok", "stCode": 403}
        with self.assertRaises(KotakSessionExpired):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)

    def test_exception_after_submit_stays_unknown(self):
        self.fake.place_response = {"error": "timeout"}
        with self.assertRaises(RuntimeError):
            self.broker.place_market_order("NSE", "RELIANCE", "BUY", 1)

    def test_square_off_attempts_every_exit_and_reports_blocked_ones(self):
        self.fake.position_rows = [
            {"trdSym": "IDEA-EQ", "exSeg": "nse_cm", "cfBuyQty": 5, "flBuyQty": 0},
            {"trdSym": "TCS-EQ", "exSeg": "nse_cm", "cfBuyQty": 3, "flBuyQty": 0},
        ]
        self.broker._rate = OrderRateGuard(max_per_second=1, clock=lambda: 9.0)
        results = self.broker.square_off_all()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["status"], "OPEN")
        self.assertEqual(results[1]["status"], "NOT_SENT")
        self.assertEqual(results[1]["error"], "OrderRateLimitExceeded")
        self.assertEqual(len(self.fake.placed()), 1)


class OrderTagTests(unittest.TestCase):
    TAG_RE = re.compile(r"^AIQ[0-9A-F]{12}$")

    def test_generated_tags_are_unique_short_and_alnum(self):
        tags = {new_order_tag() for _ in range(500)}
        self.assertEqual(len(tags), 500)
        for tag in tags:
            self.assertRegex(tag, self.TAG_RE)
            self.assertLessEqual(len(tag), 15)

    def test_each_live_order_sends_its_own_tag_and_returns_it(self):
        fake = FakeNeo(ltp=100.0)
        broker = live_broker(fake)
        broker.connect()
        first = broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        second = broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        sent = fake.placed()
        self.assertEqual(sent[0]["tag"], first["order_tag"])
        self.assertEqual(sent[1]["tag"], second["order_tag"])
        self.assertNotEqual(first["order_tag"], second["order_tag"])
        self.assertRegex(first["order_tag"], self.TAG_RE)

    def test_no_algo_field_is_sent_by_us(self):
        # Kotak Algo ID khud append karta hai; hamara payload mein koi algo field nahi jana chahiye.
        fake = FakeNeo(ltp=100.0)
        broker = live_broker(fake)
        broker.connect()
        broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertFalse(any("algo" in key.lower() for key in fake.placed()[0]))

    def test_rejected_order_still_carries_its_tag(self):
        fake = FakeNeo(ltp=100.0)
        fake.place_response = {"stat": "Not_Ok", "stCode": 1003, "emsg": "insufficient funds"}
        broker = live_broker(fake)
        broker.connect()
        order = broker.place_market_order("NSE", "RELIANCE", "BUY", 1)
        self.assertEqual(order["status"], "REJECTED")
        self.assertEqual(order["order_tag"], fake.placed()[0]["tag"])

    def test_order_report_maps_guiordid_back_to_tag(self):
        broker = live_broker(FakeNeo())
        local = broker._to_local_order({"nOrdNo": "1", "GuiOrdId": "AIQ0123456789AB", "ordSt": "open"})
        self.assertEqual(local["order_tag"], "AIQ0123456789AB")


@unittest.skipUnless(importlib.util.find_spec("neo_api_client"), "kotakneoapi not installed")
class LogRedactionTests(unittest.TestCase):
    def test_structured_sdk_event_is_scrubbed_before_handlers(self):
        from neo_api_client.logger import get_logger

        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(repr(record.msg))

        sdk = logging.getLogger("neo_api_client")
        capture = Capture()
        sdk.addHandler(capture)
        try:
            redact_sdk_logs(["+919999999999", "U1ABC", "654321"])
            get_logger("neo_api_client.rest").error(
                "api_request_connection_error",
                body={"mobileNumber": "+919999999999", "ucc": "U1ABC", "mpin": "654321"})
        finally:
            sdk.removeHandler(capture)
        self.assertEqual(len(captured), 1)
        line = captured[0]
        self.assertNotIn("+919999999999", line)
        self.assertNotIn("U1ABC", line)
        self.assertNotIn("654321", line)
        self.assertIn("***", line)


if __name__ == "__main__":
    unittest.main()
