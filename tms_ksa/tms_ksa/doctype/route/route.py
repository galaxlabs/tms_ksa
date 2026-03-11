# # Copyright (c) 2026, Galaxy Labs and contributors
# # For license information, please see license.txt


import re
import frappe
import requests
from frappe import _
from frappe.model.document import Document


class Route(Document):
    def before_naming(self):
        self.prepare_route_code()

    def before_validate(self):
        self.prepare_route_code()

    def validate(self):
        self.validate_basic_fields()
        self.validate_return_route()

    def prepare_route_code(self):
        # keep manual value if already entered
        if self.route_code:
            self.route_code = self.clean_code(self.route_code)
            return

        from_code = self.make_city_code(self.from_city)
        to_code = self.make_city_code(self.to_city)

        base_code = f"{from_code}-TO-{to_code}"
        self.route_code = self.make_unique_route_code(base_code)

    def validate_basic_fields(self):
        if not self.from_city:
            frappe.throw(_("From City is required."))

        if not self.to_city:
            frappe.throw(_("To City is required."))

        if self.from_place_full and self.to_place_full:
            if self.from_place_full.strip().lower() == self.to_place_full.strip().lower():
                frappe.throw(_("From Place and To Place cannot be the same."))

        if self.distance and float(self.distance) < 0:
            frappe.throw(_("Distance cannot be negative."))

        if self.duration_minutes and int(self.duration_minutes) < 0:
            frappe.throw(_("Duration Minutes cannot be negative."))

        if self.avg_speed_kmph and float(self.avg_speed_kmph) < 0:
            frappe.throw(_("Avg Speed cannot be negative."))

    def validate_return_route(self):
        if self.has_return and self.return_route and self.return_route == self.name:
            frappe.throw(_("Return Route cannot be the same route."))

    @staticmethod
    def normalize_city_name(city: str) -> str:
        city = (city or "").strip().lower()
        city = city.replace("-", " ")
        city = re.sub(r"\s+", " ", city)

        aliases = {
            "jidda": "jeddah",
            "jiddah": "jeddah",
            "medina": "madinah",
            "al madinah al munawwarah": "madinah",
            "madinah al munawwarah": "madinah",
            "mecca": "makkah",
            "makkah al mukarramah": "makkah",
            "al khobar": "khobar",
            "hafar al batin": "hafar",
            "king abdulaziz international airport": "jeddah",
            "prince mohammad bin abdulaziz international airport": "madinah",
            "madinah station": "madinah",
            "madina markazia": "madinah",
            "makkah principality": "makkah",
            "jeddah airport terminal 1": "jeddah",
        }

        return aliases.get(city, city)

    @classmethod
    def make_city_code(cls, city: str) -> str:
        city = cls.normalize_city_name(city)

        cleaned = re.sub(r"[^A-Za-z ]", " ", city)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            return "UNK"

        first_word = cleaned.split()[0].upper()
        if len(first_word) >= 3:
            return first_word[:3]

        joined = cleaned.replace(" ", "").upper()
        if len(joined) >= 3:
            return joined[:3]

        return (joined + "XXX")[:3]

    @staticmethod
    def clean_code(value: str) -> str:
        value = (value or "").strip().upper()
        value = re.sub(r"[^A-Z0-9\-]", "", value)
        return value

    def make_unique_route_code(self, base_code: str) -> str:
        base_code = self.clean_code(base_code)

        existing = frappe.db.get_value("Route", {"route_code": base_code}, "name")
        if not existing or existing == self.name:
            return base_code

        counter = 2
        while True:
            candidate = f"{base_code}-{counter}"
            existing = frappe.db.get_value("Route", {"route_code": candidate}, "name")
            if not existing or existing == self.name:
                return candidate
            counter += 1

    @staticmethod
    def clean_place_name(name: str) -> str:
        if not name:
            return ""
        name = name.replace(", Saudi Arabia", "").replace(", United Arab Emirates", "").strip()
        return name.split(",")[0]

    @staticmethod
    def get_place_name(place: str, api_key: str):
        """Get place name in English + Arabic"""
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            "input": place,
            "inputtype": "textquery",
            "fields": "place_id",
            "key": api_key,
        }
        res = requests.get(url, params=params, timeout=20).json()
        if not res.get("candidates"):
            return Route.clean_place_name(place)

        place_id = res["candidates"][0]["place_id"]

        details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        params_en = {"place_id": place_id, "fields": "name", "language": "en", "key": api_key}
        en_data = requests.get(details_url, params=params_en, timeout=20).json()
        en_name = en_data.get("result", {}).get("name", place)

        params_ar = {"place_id": place_id, "fields": "name", "language": "ar", "key": api_key}
        ar_data = requests.get(details_url, params=params_ar, timeout=20).json()
        ar_name = ar_data.get("result", {}).get("name", "")

        return f"{en_name} | {ar_name}" if ar_name else en_name


def _get_api_key():
    api_key = frappe.conf.get("google_maps_api_key")
    if not api_key:
        try:
            settings = frappe.get_single("Google Map Settings")
            api_key = settings.api_key
        except Exception:
            pass

    if not api_key:
        frappe.throw("Google Maps API key not found. Add it in site_config.json or Google Map Settings.")

    return api_key


def _parse_distance_km(distance_text: str) -> float:
    dt = (distance_text or "").lower().replace(",", "").strip()
    if " km" in dt:
        return float(dt.replace(" km", ""))
    if " m" in dt:
        return float(dt.replace(" m", "")) / 1000
    return float("".join(ch for ch in dt if (ch.isdigit() or ch == ".")))


@frappe.whitelist()
def fetch_distance_for_route(route_name: str):
    """
    Fetch distance & duration_minutes for a saved Route and update it.
    Uses Route.avg_speed_kmph if set, else fallback to 100.
    Also updates readable place names from Google.
    """
    if not route_name:
        frappe.throw("Route name is required")

    route = frappe.get_doc("Route", route_name)

    if not route.from_city or not route.to_city:
        frappe.throw("Please set From City and To City first")

    api_key = _get_api_key()

    base_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": route.from_city,
        "destinations": route.to_city,
        "key": api_key,
        "region": "sa",
    }

    res = requests.get(base_url, params=params, timeout=20)
    data = res.json()

    if data.get("status") != "OK":
        frappe.throw(f"Google API Error: {data.get('status')}")

    el = data["rows"][0]["elements"][0]
    if el.get("status") != "OK":
        frappe.throw(f"Distance Matrix Error: {el.get('status')}")

    distance_text = el["distance"]["text"]
    distance_km = _parse_distance_km(distance_text)

    avg_speed = float(route.avg_speed_kmph or 0) or 100.0
    duration_minutes = max(1, int(round((distance_km / avg_speed) * 60)))

    route.db_set("distance", distance_km)
    route.db_set("duration_minutes", duration_minutes)
    route.db_set("from_place_full", Route.get_place_name(route.from_city, api_key))
    route.db_set("to_place_full", Route.get_place_name(route.to_city, api_key))

    try:
        route.db_set("duration", f"{(duration_minutes / 60):.2f} hrs")
    except Exception:
        pass

    return {
        "route": route.name,
        "route_code": route.route_code,
        "distance": distance_km,
        "duration_minutes": duration_minutes,
        "avg_speed_used": avg_speed,
    }



