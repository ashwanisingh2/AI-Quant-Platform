"""ATM Call Buyer strategy — F&O options BUYING only (safe direction). 📈⚠️

Rule: Option premium ka fast EMA slow EMA ko upar cross kare → CE BUY karo.
      Neeche cross kare → position band karo (long exit).

⚠️ Ye strategy sirf options BUY karta hai — naked selling nahi.
   Risk engine bhi naked option SELL block karta hai (double safety).

Strike selection: user jis option instrument pe chalaye (ya chain se ATM pick kare —
libs.shared.fno.atm_strike helper hai).
"""
from __future__ import annotations

from apps.engine.strategies.ema_cross import EMACross, EMACrossConfig


class ATMCallBuyConfig(EMACrossConfig):
    """Same params as EMA cross — bas naam F&O intent batata hai."""


class ATMCallBuy(EMACross):
    """EMA crossover on option premium — options buyer.

    EMACross se inherit kiya — logic same, intent clear:
    BUY = long option (premium pay ki), SELL = long exit.
    """
