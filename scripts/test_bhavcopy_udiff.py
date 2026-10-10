import io
import unittest
import zipfile
from datetime import date
from unittest.mock import Mock, patch

from apps.data_gateway.providers.bhavcopy_provider import BhavcopyProvider


class UdiffTests(unittest.TestCase):
    def archive(self, trading_date='2026-10-09'):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('daily.csv', 'TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n'
                             f'{trading_date},INFY,EQ,100,110,90,105,1000\n')
        return buffer.getvalue()

    def test_current_format_and_prices(self):
        provider = BhavcopyProvider()
        response = Mock(status_code=200, content=self.archive())
        with patch('apps.data_gateway.providers.bhavcopy_provider.requests.get', return_value=response) as request:
            candles = provider.fetch_eod('INFY', date(2026, 10, 9))
        self.assertEqual(candles[0].close, 105)
        self.assertEqual(candles[0].volume, 1000)
        self.assertIn('20261009_F_0000.csv.zip', request.call_args.args[0])

    def test_wrong_session_not_relabelled(self):
        response = Mock(status_code=200, content=self.archive('2026-10-08'))
        with patch('apps.data_gateway.providers.bhavcopy_provider.requests.get', return_value=response):
            self.assertEqual(BhavcopyProvider().fetch_eod('INFY', date(2026, 10, 9)), [])

    def test_unsupported_exchange_rejected(self):
        with self.assertRaises(ValueError):
            BhavcopyProvider().get_historical('INFY', exchange='BSE')


if __name__ == '__main__':
    unittest.main()
