"""
Gateway Payment Service
Handles interactions with various payment gateways (ZarinPal, Stripe, PaddlePay, etc.)
"""

import os
import json
from typing import Optional
from fastapi import HTTPException

# ========== ZarinPal Gateway ==========

ZARINPAL_MERCHANT_ID = os.getenv("ZARINPAL_MERCHANT_ID", "test")
ZARINPAL_SANDBOX = os.getenv("ZARINPAL_SANDBOX", "true").lower() == "true"
ZARINPAL_API_URL = "https://sandbox.zarinpal.com/pg/v4" if ZARINPAL_SANDBOX else "https://www.zarinpal.com/pg/v4"


class ZarinPalGateway:
    """ZarinPal payment gateway integration"""

    @staticmethod
    def get_payment_url(authority: str, amount: int) -> str:
        """
        Generate ZarinPal payment redirect URL
        User redirects to this URL to complete payment
        """
        host = "sandbox.zarinpal.com" if ZARINPAL_SANDBOX else "www.zarinpal.com"
        return f"https://{host}/pg/StartPay/{authority}"

    @staticmethod
    def build_payment_link(authority: str) -> dict:
        """
        Return payment initiation data for ZarinPal
        Frontend or app will redirect user to payment_url
        """
        return {
            "gateway": "zarinpal",
            "payment_url": ZarinPalGateway.get_payment_url(authority, 0),
            "authority": authority,
            "instructions": {
                "step1": "User redirects to payment_url",
                "step2": "After payment, user is redirected back with authority code",
                "step3": "Frontend calls /finance/gateway/verify with authority and ref_id",
            }
        }


# ========== Stripe Gateway ==========

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")


class StripeGateway:
    """Stripe payment gateway integration"""

    @staticmethod
    def get_payment_session_url(payment_id: str) -> str:
        """
        Generate Stripe Checkout Session URL
        Note: Requires actual Stripe implementation
        """
        return f"https://checkout.stripe.com/pay/{payment_id}"

    @staticmethod
    def build_payment_link(authority: str) -> dict:
        """Return payment initiation data for Stripe"""
        return {
            "gateway": "stripe",
            "authority": authority,
            "publishable_key": STRIPE_PUBLISHABLE_KEY,
            "instructions": {
                "step1": "Use Stripe.js to initialize checkout with authority",
                "step2": "After payment, Stripe webhook notifies backend",
                "step3": "Backend automatically verifies and credits wallet",
            }
        }


# ========== PaddlePay Gateway ==========

PADDLEPAY_API_KEY = os.getenv("PADDLEPAY_API_KEY", "")
PADDLEPAY_VENDOR_ID = os.getenv("PADDLEPAY_VENDOR_ID", "")


class PaddlePayGateway:
    """PaddlePay payment gateway integration"""

    @staticmethod
    def get_payment_url(authority: str) -> str:
        """
        Generate PaddlePay payment URL
        """
        return f"https://checkout.paddle.com/{authority}"

    @staticmethod
    def build_payment_link(authority: str) -> dict:
        """Return payment initiation data for PaddlePay"""
        return {
            "gateway": "paddlepay",
            "payment_url": PaddlePayGateway.get_payment_url(authority),
            "authority": authority,
            "instructions": {
                "step1": "User redirects to payment_url",
                "step2": "After payment, PaddlePay webhooks notify backend",
                "step3": "Backend verifies webhook and credits wallet",
            }
        }


# ========== Gateway Factory ==========

class GatewayFactory:
    """Factory for getting the correct gateway handler"""

    GATEWAYS = {
        "zarinpal": ZarinPalGateway,
        "stripe": StripeGateway,
        "paddlepay": PaddlePayGateway,
    }

    @staticmethod
    def get_gateway(gateway_name: str):
        """Get gateway handler by name"""
        if gateway_name not in GatewayFactory.GATEWAYS:
            raise HTTPException(
                status_code=400,
                detail=f"Gateway '{gateway_name}' not supported. Choose from: {list(GatewayFactory.GATEWAYS.keys())}"
            )
        return GatewayFactory.GATEWAYS[gateway_name]

    @staticmethod
    def build_payment_link(gateway: str, authority: str, amount: int) -> dict:
        """Build payment link for a gateway"""
        gateway_handler = GatewayFactory.get_gateway(gateway)
        payment_data = gateway_handler.build_payment_link(authority)
        payment_data["amount"] = amount  # Add amount to response
        return payment_data


# ========== Helper Functions ==========

def format_amount_for_gateway(amount: int, gateway: str) -> int:
    """
    Convert amount to gateway's required format
    Some gateways require different unit conversions
    """
    if gateway == "stripe":
        # Stripe uses cents
        return amount // 100 if amount >= 100 else amount
    return amount  # Others use default (Toman for Iranian gateways)


def get_supported_gateways() -> list[str]:
    """Get list of supported payment gateways"""
    return list(GatewayFactory.GATEWAYS.keys())
