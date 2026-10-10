"""Kotak Neo broker adapter — offline tests with a fake SDK client (no network, no orders).

Run: python -m unittest scripts.test_kotak_broker
"""
import unittest

from apps.engine.brokers import available_brokers, get_broker
from apps.engine.brokers.kotak_broker import KotakBroker, _marketable_limit


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
        return [{"pTrdSymbol": "RELIANCE-EQ", "pSymbol": "2885"},
                {"pTrdSymbol": "RELIANCE-BE", "pSymbol": "9999"}]

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


if __name__ == "__main__":
    unittest.main()
