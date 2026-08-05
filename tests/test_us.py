"""
tests/test_us.py — Smoke & Integration Tests for US Trading Stack
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import config
from us_instruments import get_us_security_id, is_us_symbol, get_all_us_symbols
from us_paper import USPaperPortfolio
from us_broker import USBroker
from dashboard_server import app


class TestUSInstruments(unittest.TestCase):
    def test_symbols_exist(self):
        symbols = get_all_us_symbols()
        self.assertIn("AAPL", symbols)
        self.assertIn("NVDA", symbols)
        self.assertTrue(is_us_symbol("AAPL"))
        self.assertIsNotNone(get_us_security_id("AAPL"))


class TestUSPaperPortfolio(unittest.TestCase):
    def setUp(self):
        self.portfolio = USPaperPortfolio(starting_cash=10000.0)
        self.portfolio.reset(starting_cash=10000.0)

    def test_buy_and_sell(self):
        # Initial cash
        info = self.portfolio.get_account_info()
        self.assertEqual(info["available_cash"], 10000.0)

        # Buy 10 AAPL @ $150
        order_id = self.portfolio.buy("AAPL", 10, 150.0, stop_loss=140.0, take_profit=170.0)
        self.assertIsNotNone(order_id)
        self.assertTrue(order_id.startswith("US-PAPER-"))

        # Cash check
        info = self.portfolio.get_account_info({"AAPL": 150.0})
        self.assertEqual(info["available_cash"], 8500.0)
        self.assertEqual(info["equity"], 10000.0)

        # Open positions check
        positions = self.portfolio.get_open_positions({"AAPL": 160.0})
        self.assertIn("AAPL", positions)
        self.assertEqual(positions["AAPL"]["qty"], 10)
        self.assertEqual(positions["AAPL"]["unrealized_pl"], 100.0)

        # Sell 5 AAPL @ $160
        sell_id = self.portfolio.sell("AAPL", 5, 160.0)
        self.assertIsNotNone(sell_id)

        # Remaining position
        positions = self.portfolio.get_open_positions({"AAPL": 160.0})
        self.assertEqual(positions["AAPL"]["qty"], 5)

        # Clean up
        self.portfolio.reset()


class TestUSBrokerSafety(unittest.TestCase):
    def test_live_gate_blocked_by_default(self):
        with patch.object(config, "US_LIVE_CONFIRMED", False), \
             patch.object(config, "US_PAPER", False):
            broker = USBroker(auto_login=False)
            broker.paper = None  # Force live mode test
            order_id = broker.place_buy_order("AAPL", 10, 150.0)
            self.assertIsNone(order_id)
            self.assertIn("Live trading not confirmed", broker.last_error)


class TestUSDashboardRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_us_status_endpoint(self):
        res = self.client.get("/api/us/status")
        self.assertEqual(res.status_code, 200)

    def test_us_positions_endpoint(self):
        res = self.client.get("/api/us/positions")
        self.assertEqual(res.status_code, 200)

    def test_us_scanner_endpoint(self):
        res = self.client.get("/api/us/scanner")
        self.assertEqual(res.status_code, 200)

    def test_us_toggle_kill_switch(self):
        res = self.client.post("/api/us/toggle_kill_switch")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_health_endpoint_includes_us(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("us_enabled", data)
        self.assertIn("us_kill_switch", data)


if __name__ == "__main__":
    unittest.main()
