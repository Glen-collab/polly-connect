"""
Stripe subscription management for Polly Connect.

Tiers:
  - trial: 30-day free trial (limited stories/photos/items)
  - basic: $9.99/mo or $99/yr — unlimited stories, no book export
  - legacy: $19.99/mo or $199/yr — full access including book export

Feature gating is based on tenant subscription_tier + subscription_status.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

# Lazy-load stripe to avoid import errors if not installed
_stripe = None


def _get_stripe():
    global _stripe
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            _stripe = stripe
        except ImportError:
            logger.error("stripe package not installed — run: pip install stripe")
            return None
    return _stripe


# ── Tier definitions ──

TIERS = {
    "trial": {
        "name": "Free Trial",
        "max_stories": 10,
        "max_photos": 5,
        "max_items": 10,
        "max_photo_stories": 3,
        "max_family_codes": 1,
        "max_devices": 1,
        "book_preview_chapters": 2,
        "book_export": False,
        "book_qr_codes": False,
        "phone_recording": True,
        "family_tree_edit": False,
        "nostalgia_limit": 5,
    },
    "basic": {
        "name": "Polly Basic",
        "max_stories": 99999,
        "max_photos": 99999,
        "max_items": 99999,
        "max_photo_stories": 99999,
        "max_family_codes": 3,
        "max_devices": 1,
        "book_preview_chapters": 2,
        "book_export": False,
        "book_qr_codes": False,
        "phone_recording": True,
        "family_tree_edit": True,
        "nostalgia_limit": 99999,
    },
    "legacy": {
        "name": "Polly Legacy",
        "max_stories": 99999,
        "max_photos": 99999,
        "max_items": 99999,
        "max_photo_stories": 99999,
        "max_family_codes": 99999,
        "max_devices": 3,
        "book_preview_chapters": 99999,
        "book_export": True,
        "book_qr_codes": True,
        "phone_recording": True,
        "family_tree_edit": True,
        "nostalgia_limit": 99999,
    },
}

# Admin tenant (id=1) always has full access
ADMIN_TENANT_ID = 1


def get_tier_limits(tier: str) -> Dict:
    """Get feature limits for a subscription tier."""
    return TIERS.get(tier, TIERS["trial"])


def check_feature(db, tenant_id: int, feature: str) -> bool:
    """Check if a tenant can use a specific feature.

    Features: 'add_story', 'add_photo', 'add_item', 'add_photo_story',
              'book_export', 'book_qr', 'phone_recording', 'family_tree_edit'
    """
    # Admin always has full access
    if tenant_id == ADMIN_TENANT_ID:
        return True

    sub = get_subscription(db, tenant_id)
    tier = sub["tier"]
    status = sub["status"]

    # Expired trial or canceled — read-only
    if status in ("expired", "canceled", "past_due"):
        return False

    limits = get_tier_limits(tier)

    if feature == "add_story":
        count = _count_stories(db, tenant_id)
        return count < limits["max_stories"]
    elif feature == "add_photo":
        count = _count_photos(db, tenant_id)
        return count < limits["max_photos"]
    elif feature == "add_item":
        count = _count_items(db, tenant_id)
        return count < limits["max_items"]
    elif feature == "add_photo_story":
        count = _count_photo_stories(db, tenant_id)
        return count < limits["max_photo_stories"]
    elif feature == "book_export":
        return limits["book_export"]
    elif feature == "book_qr":
        return limits["book_qr_codes"]
    elif feature == "phone_recording":
        return limits["phone_recording"]
    elif feature == "family_tree_edit":
        return limits["family_tree_edit"]

    return True


def get_subscription(db, tenant_id: int) -> Dict:
    """Get the current subscription state for a tenant."""
    if tenant_id == ADMIN_TENANT_ID:
        return {"tier": "legacy", "status": "active", "trial_days_left": None}

    conn = db._get_connection()
    try:
        import sqlite3
        conn.row_factory = sqlite3.Row
        tenant = conn.execute(
            "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        if not tenant:
            return {"tier": "trial", "status": "active", "trial_days_left": 30}

        tenant = dict(tenant)
        tier = tenant.get("subscription_tier") or "trial"
        status = tenant.get("subscription_status") or "active"
        trial_end = tenant.get("trial_ends_at")

        # Check if trial has expired
        if tier == "trial" and trial_end:
            try:
                end_dt = datetime.fromisoformat(trial_end)
                if datetime.utcnow() > end_dt:
                    status = "expired"
                    # Update DB
                    conn.execute(
                        "UPDATE tenants SET subscription_status = 'expired' WHERE id = ?",
                        (tenant_id,)
                    )
                    conn.commit()
                else:
                    days_left = (end_dt - datetime.utcnow()).days
                    return {"tier": tier, "status": "active",
                            "trial_days_left": max(0, days_left),
                            "stripe_customer_id": tenant.get("stripe_customer_id")}
            except (ValueError, TypeError):
                pass

        return {
            "tier": tier,
            "status": status,
            "trial_days_left": None,
            "stripe_customer_id": tenant.get("stripe_customer_id"),
            "stripe_subscription_id": tenant.get("stripe_subscription_id"),
        }
    finally:
        if not db._conn:
            conn.close()


def start_trial(db, tenant_id: int, days: int = 30):
    """Start a free trial for a tenant."""
    trial_end = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE tenants SET subscription_tier = 'trial',
                subscription_status = 'active', trial_ends_at = ?
            WHERE id = ?
        """, (trial_end, tenant_id))
        conn.commit()
        logger.info(f"Started {days}-day trial for tenant {tenant_id}")
    finally:
        if not db._conn:
            conn.close()


def create_checkout_session(db, tenant_id: int, tier: str,
                             interval: str = "month",
                             success_url: str = None,
                             cancel_url: str = None) -> Optional[str]:
    """Create a Stripe Checkout Session and return the URL.

    tier: 'basic' or 'legacy'
    interval: 'month' or 'year'
    """
    stripe = _get_stripe()
    if not stripe:
        return None

    # Price lookup — we create products/prices on the fly if needed
    price_id = _get_or_create_price(stripe, tier, interval)
    if not price_id:
        return None

    # Get or create Stripe customer
    customer_id = _get_or_create_customer(stripe, db, tenant_id)

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url or "https://polly-connect.com/web/billing?success=1",
            cancel_url=cancel_url or "https://polly-connect.com/web/pricing",
            metadata={"tenant_id": str(tenant_id), "tier": tier},
        )
        return session.url
    except Exception as e:
        logger.error(f"Stripe checkout session failed: {e}")
        return None


def create_billing_portal_session(db, tenant_id: int,
                                   return_url: str = None) -> Optional[str]:
    """Create a Stripe Billing Portal session for managing subscription."""
    stripe = _get_stripe()
    if not stripe:
        return None

    conn = db._get_connection()
    try:
        customer_id = conn.execute(
            "SELECT stripe_customer_id FROM tenants WHERE id = ?",
            (tenant_id,)
        ).fetchone()
        if not customer_id or not customer_id[0]:
            return None
        customer_id = customer_id[0]
    finally:
        if not db._conn:
            conn.close()

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or "https://polly-connect.com/web/billing",
        )
        return session.url
    except Exception as e:
        logger.error(f"Stripe billing portal failed: {e}")
        return None


def handle_webhook_event(db, event) -> bool:
    """Process a Stripe webhook event. Returns True if handled."""
    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        tenant_id = int(data.get("metadata", {}).get("tenant_id", 0))
        tier = data.get("metadata", {}).get("tier", "basic")
        subscription_id = data.get("subscription")
        if tenant_id and subscription_id:
            _activate_subscription(db, tenant_id, tier, subscription_id)
            logger.info(f"Subscription activated: tenant={tenant_id} tier={tier}")
            return True

    elif event_type == "customer.subscription.updated":
        _sync_subscription_status(db, data)
        return True

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_canceled(db, data)
        return True

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        if customer_id:
            _mark_past_due(db, customer_id)
        return True

    elif event_type == "invoice.paid":
        customer_id = data.get("customer")
        if customer_id:
            _mark_active(db, customer_id)
        return True

    return False


# ── Internal helpers ──

def _count_stories(db, tenant_id: int) -> int:
    conn = db._get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM stories WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
    finally:
        if not db._conn:
            conn.close()


def _count_photos(db, tenant_id: int) -> int:
    conn = db._get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM photos WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
    finally:
        if not db._conn:
            conn.close()


def _count_items(db, tenant_id: int) -> int:
    conn = db._get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM items WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
    finally:
        if not db._conn:
            conn.close()


def _count_photo_stories(db, tenant_id: int) -> int:
    conn = db._get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM stories WHERE tenant_id = ? AND photo_id IS NOT NULL",
            (tenant_id,)
        ).fetchone()[0]
    finally:
        if not db._conn:
            conn.close()


# Product/Price IDs cached after first creation
_price_cache = {}

PRICE_CONFIG = {
    ("basic", "month"): {"amount": 999, "name": "Polly Basic Monthly"},
    ("basic", "year"): {"amount": 9900, "name": "Polly Basic Annual"},
    ("legacy", "month"): {"amount": 1999, "name": "Polly Legacy Monthly"},
    ("legacy", "year"): {"amount": 19900, "name": "Polly Legacy Annual"},
}


def _get_or_create_price(stripe, tier: str, interval: str) -> Optional[str]:
    """Get or create a Stripe Price for the given tier and interval."""
    cache_key = (tier, interval)
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    config = PRICE_CONFIG.get(cache_key)
    if not config:
        return None

    try:
        # Search for existing product
        products = stripe.Product.search(query=f"name:'{config['name']}'")
        if products.data:
            product = products.data[0]
        else:
            product = stripe.Product.create(
                name=config["name"],
                description=f"Polly Connect - {TIERS[tier]['name']}",
            )

        # Search for existing price on this product
        prices = stripe.Price.list(product=product.id, active=True)
        for p in prices.data:
            if (p.unit_amount == config["amount"]
                    and p.recurring
                    and p.recurring.interval == interval):
                _price_cache[cache_key] = p.id
                return p.id

        # Create new price
        price = stripe.Price.create(
            product=product.id,
            unit_amount=config["amount"],
            currency="usd",
            recurring={"interval": interval},
        )
        _price_cache[cache_key] = price.id
        return price.id
    except Exception as e:
        logger.error(f"Stripe price creation failed: {e}")
        return None


def _get_or_create_customer(stripe, db, tenant_id: int) -> str:
    """Get existing Stripe customer or create one for this tenant."""
    conn = db._get_connection()
    try:
        row = conn.execute(
            "SELECT stripe_customer_id FROM tenants WHERE id = ?",
            (tenant_id,)
        ).fetchone()
        if row and row[0]:
            return row[0]

        # Get account email for this tenant
        account = conn.execute(
            "SELECT email, name FROM accounts WHERE tenant_id = ? LIMIT 1",
            (tenant_id,)
        ).fetchone()
        email = account[0] if account else None
        name = account[1] if account else None

        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"tenant_id": str(tenant_id)},
        )

        conn.execute(
            "UPDATE tenants SET stripe_customer_id = ? WHERE id = ?",
            (customer.id, tenant_id)
        )
        conn.commit()
        return customer.id
    finally:
        if not db._conn:
            conn.close()


def _activate_subscription(db, tenant_id: int, tier: str, subscription_id: str):
    """Activate a subscription after successful checkout."""
    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE tenants SET subscription_tier = ?, subscription_status = 'active',
                stripe_subscription_id = ?, trial_ends_at = NULL
            WHERE id = ?
        """, (tier, subscription_id, tenant_id))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()


def _sync_subscription_status(db, subscription_data):
    """Sync subscription status from Stripe webhook."""
    customer_id = subscription_data.get("customer")
    status = subscription_data.get("status")  # active, past_due, canceled, etc.

    conn = db._get_connection()
    try:
        if status == "active":
            conn.execute(
                "UPDATE tenants SET subscription_status = 'active' WHERE stripe_customer_id = ?",
                (customer_id,)
            )
        elif status in ("past_due", "unpaid"):
            conn.execute(
                "UPDATE tenants SET subscription_status = 'past_due' WHERE stripe_customer_id = ?",
                (customer_id,)
            )
        elif status == "canceled":
            conn.execute(
                "UPDATE tenants SET subscription_status = 'canceled', subscription_tier = 'trial' WHERE stripe_customer_id = ?",
                (customer_id,)
            )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()


def _handle_subscription_canceled(db, subscription_data):
    """Handle subscription cancellation."""
    customer_id = subscription_data.get("customer")
    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE tenants SET subscription_status = 'canceled',
                stripe_subscription_id = NULL
            WHERE stripe_customer_id = ?
        """, (customer_id,))
        conn.commit()
        logger.info(f"Subscription canceled for customer {customer_id}")
    finally:
        if not db._conn:
            conn.close()


def _mark_past_due(db, customer_id: str):
    conn = db._get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET subscription_status = 'past_due' WHERE stripe_customer_id = ?",
            (customer_id,)
        )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()


def _mark_active(db, customer_id: str):
    conn = db._get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET subscription_status = 'active' WHERE stripe_customer_id = ?",
            (customer_id,)
        )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()
