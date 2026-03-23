from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StateInfo:
    code: str
    name: str
    fips_code: str
    implemented: bool = False


STATE_REGISTRY: dict[str, StateInfo] = {
    "AL": StateInfo("AL", "Alabama", "01"),
    "AK": StateInfo("AK", "Alaska", "02"),
    "AZ": StateInfo("AZ", "Arizona", "04"),
    "AR": StateInfo("AR", "Arkansas", "05"),
    "CA": StateInfo("CA", "California", "06"),
    "CO": StateInfo("CO", "Colorado", "08"),
    "CT": StateInfo("CT", "Connecticut", "09"),
    "DE": StateInfo("DE", "Delaware", "10", implemented=True),
    "FL": StateInfo("FL", "Florida", "12"),
    "GA": StateInfo("GA", "Georgia", "13"),
    "HI": StateInfo("HI", "Hawaii", "15"),
    "ID": StateInfo("ID", "Idaho", "16"),
    "IL": StateInfo("IL", "Illinois", "17"),
    "IN": StateInfo("IN", "Indiana", "18"),
    "IA": StateInfo("IA", "Iowa", "19"),
    "KS": StateInfo("KS", "Kansas", "20"),
    "KY": StateInfo("KY", "Kentucky", "21"),
    "LA": StateInfo("LA", "Louisiana", "22"),
    "ME": StateInfo("ME", "Maine", "23"),
    "MD": StateInfo("MD", "Maryland", "24"),
    "MA": StateInfo("MA", "Massachusetts", "25"),
    "MI": StateInfo("MI", "Michigan", "26"),
    "MN": StateInfo("MN", "Minnesota", "27"),
    "MS": StateInfo("MS", "Mississippi", "28"),
    "MO": StateInfo("MO", "Missouri", "29"),
    "MT": StateInfo("MT", "Montana", "30"),
    "NE": StateInfo("NE", "Nebraska", "31"),
    "NV": StateInfo("NV", "Nevada", "32"),
    "NH": StateInfo("NH", "New Hampshire", "33"),
    "NJ": StateInfo("NJ", "New Jersey", "34"),
    "NM": StateInfo("NM", "New Mexico", "35"),
    "NY": StateInfo("NY", "New York", "36"),
    "NC": StateInfo("NC", "North Carolina", "37"),
    "ND": StateInfo("ND", "North Dakota", "38"),
    "OH": StateInfo("OH", "Ohio", "39"),
    "OK": StateInfo("OK", "Oklahoma", "40"),
    "OR": StateInfo("OR", "Oregon", "41"),
    "PA": StateInfo("PA", "Pennsylvania", "42", implemented=True),
    "RI": StateInfo("RI", "Rhode Island", "44"),
    "SC": StateInfo("SC", "South Carolina", "45"),
    "SD": StateInfo("SD", "South Dakota", "46"),
    "TN": StateInfo("TN", "Tennessee", "47"),
    "TX": StateInfo("TX", "Texas", "48"),
    "UT": StateInfo("UT", "Utah", "49"),
    "VT": StateInfo("VT", "Vermont", "50"),
    "VA": StateInfo("VA", "Virginia", "51"),
    "WA": StateInfo("WA", "Washington", "53"),
    "WV": StateInfo("WV", "West Virginia", "54"),
    "WI": StateInfo("WI", "Wisconsin", "55"),
    "WY": StateInfo("WY", "Wyoming", "56"),
}
