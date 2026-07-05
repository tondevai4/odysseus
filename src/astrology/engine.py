"""Vedic astrology engine using Swiss Ephemeris."""

import datetime
from typing import Any, Dict, List

import swisseph as swe

# Set sidereal mode to Lahiri Ayanamsa
swe.set_sid_mode(swe.SIDM_LAHIRI)

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,
}

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]


def _get_julian_day(date_str: str) -> float:
    """Convert ISO date string to Julian Day."""
    # Assuming date_str is YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ
    try:
        if "T" in date_str:
            dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = datetime.datetime.fromisoformat(date_str)
        # Convert to UTC if timezone aware
        if dt.tzinfo:
            dt = dt.astimezone(datetime.timezone.utc)
        return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0)
    except Exception:
        # Fallback to current UTC
        dt = datetime.datetime.now(datetime.timezone.utc)
        return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0)


def get_transits(date_str: str) -> Dict[str, Any]:
    """Get planetary transits for a given date in Sidereal Zodiac (Lahiri)."""
    jd = _get_julian_day(date_str)
    
    transits = {}
    for name, p_id in PLANETS.items():
        # Get planetary position with SEFLG_SIDEREAL flag
        res, ret = swe.calc_ut(jd, p_id, swe.FLG_SIDEREAL | swe.FLG_SPEED)
        longitude = res[0]
        speed = res[3]
        
        sign_index = int(longitude / 30.0) % 12
        degree_in_sign = longitude % 30.0
        
        is_retrograde = speed < 0
        
        transits[name] = {
            "sign": ZODIAC_SIGNS[sign_index],
            "degree": round(degree_in_sign, 2),
            "retrograde": is_retrograde,
        }
        
    # Calculate Ketu (opposite to Rahu)
    rahu_lon = swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SIDEREAL | swe.FLG_SPEED)[0][0]
    ketu_lon = (rahu_lon + 180.0) % 360.0
    k_sign_index = int(ketu_lon / 30.0) % 12
    k_degree = ketu_lon % 30.0
    transits["Ketu"] = {
        "sign": ZODIAC_SIGNS[k_sign_index],
        "degree": round(k_degree, 2),
        "retrograde": True,  # Nodes are always retrograde functionally
    }
    
    return transits


def is_mercury_retrograde(date_str: str) -> bool:
    """Check if Mercury is currently retrograde."""
    jd = _get_julian_day(date_str)
    res, ret = swe.calc_ut(jd, swe.MERCURY, swe.FLG_SPEED)
    return res[3] < 0  # Speed is negative


def get_birth_chart(date_str: str, time_str: str, lat: float = 0.0, lon: float = 0.0) -> Dict[str, Any]:
    """Calculate basic Vedic birth chart."""
    if not date_str:
        return {}
    
    try:
        if time_str:
            iso_str = f"{date_str}T{time_str}:00Z"
        else:
            iso_str = f"{date_str}T12:00:00Z"
        jd = _get_julian_day(iso_str)
    except Exception:
        iso_str = date_str
        jd = _get_julian_day(date_str)
        
    placements = get_transits(iso_str)
    
    # If lat/lon provided, calculate Ascendant
    if lat != 0.0 and lon != 0.0:
        res, ret = swe.houses(jd, lat, lon, b'W') # Whole sign houses
        asc_lon = res[0]
        # Convert Ascendant to sidereal
        ayanamsa = swe.get_ayanamsa(jd)
        sid_asc_lon = (asc_lon - ayanamsa) % 360.0
        
        asc_sign_idx = int(sid_asc_lon / 30.0) % 12
        asc_degree = sid_asc_lon % 30.0
        
        placements["Ascendant"] = {
            "sign": ZODIAC_SIGNS[asc_sign_idx],
            "degree": round(asc_degree, 2)
        }
        
    return placements
