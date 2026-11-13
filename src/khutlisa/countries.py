"""Country names and rough centre points, used to draw the opening map and to read register country codes.

The centre points are approximate (to about a degree) and are only used to aim an arc at a country.
"""
from __future__ import annotations

# ISO alpha-2, ISO alpha-3, latitude, longitude, name.
_TABLE = """
AD AND 42.5 1.5 Andorra
AE ARE 24.0 54.0 United Arab Emirates
AF AFG 33.9 67.7 Afghanistan
AG ATG 17.1 -61.8 Antigua and Barbuda
AI AIA 18.2 -63.1 Anguilla
AL ALB 41.2 20.2 Albania
AM ARM 40.1 45.0 Armenia
AO AGO -11.2 17.9 Angola
AR ARG -34.0 -64.0 Argentina
AS ASM -14.3 -170.7 American Samoa
AT AUT 47.5 14.6 Austria
AU AUS -25.3 133.8 Australia
AW ABW 12.5 -70.0 Aruba
AZ AZE 40.1 47.6 Azerbaijan
BA BIH 43.9 17.7 Bosnia and Herzegovina
BB BRB 13.2 -59.5 Barbados
BD BGD 23.7 90.4 Bangladesh
BE BEL 50.5 4.5 Belgium
BF BFA 12.2 -1.6 Burkina Faso
BG BGR 42.7 25.5 Bulgaria
BH BHR 26.0 50.6 Bahrain
BI BDI -3.4 29.9 Burundi
BJ BEN 9.3 2.3 Benin
BM BMU 32.3 -64.8 Bermuda
BN BRN 4.5 114.7 Brunei
BO BOL -16.3 -63.6 Bolivia
BR BRA -10.0 -52.0 Brazil
BS BHS 24.7 -77.9 Bahamas
BT BTN 27.5 90.4 Bhutan
BW BWA -22.3 24.7 Botswana
BY BLR 53.7 27.9 Belarus
BZ BLZ 17.2 -88.5 Belize
CA CAN 56.1 -106.3 Canada
CD COD -2.9 23.7 Democratic Republic of the Congo
CF CAF 6.6 20.9 Central African Republic
CG COG -0.2 15.8 Republic of the Congo
CH CHE 46.8 8.2 Switzerland
CI CIV 7.5 -5.5 Ivory Coast
CL CHL -33.5 -70.7 Chile
CM CMR 5.7 12.7 Cameroon
CN CHN 35.0 105.0 China
CO COL 4.6 -74.1 Colombia
CR CRI 9.7 -83.8 Costa Rica
CU CUB 21.5 -79.0 Cuba
CV CPV 16.0 -24.0 Cape Verde
CW CUW 12.2 -69.0 Curacao
CX CXR -10.5 105.7 Christmas Island
CY CYP 35.1 33.4 Cyprus
CZ CZE 49.8 15.5 Czechia
DE DEU 51.2 10.4 Germany
DJ DJI 11.8 42.6 Djibouti
DK DNK 56.0 10.0 Denmark
DM DMA 15.4 -61.4 Dominica
DO DOM 18.7 -70.2 Dominican Republic
DZ DZA 28.0 2.6 Algeria
EC ECU -1.8 -78.2 Ecuador
EE EST 58.6 25.0 Estonia
EG EGY 26.8 30.8 Egypt
ER ERI 15.2 39.8 Eritrea
ES ESP 40.4 -3.7 Spain
ET ETH 9.1 40.5 Ethiopia
FI FIN 64.0 26.0 Finland
FJ FJI -17.7 178.1 Fiji
FM FSM 6.9 158.2 Micronesia
FO FRO 62.0 -6.9 Faroe Islands
FR FRA 46.6 2.4 France
GA GAB -0.8 11.6 Gabon
GB GBR 54.0 -2.0 United Kingdom
GD GRD 12.1 -61.7 Grenada
GE GEO 42.3 43.4 Georgia
GF GUF 4.0 -53.0 French Guiana
GG GGY 49.5 -2.6 Guernsey
GH GHA 7.9 -1.0 Ghana
GI GIB 36.1 -5.4 Gibraltar
GL GRL 72.0 -40.0 Greenland
GM GMB 13.4 -15.3 Gambia
GN GIN 9.9 -9.7 Guinea
GP GLP 16.2 -61.6 Guadeloupe
GQ GNQ 1.6 10.3 Equatorial Guinea
GR GRC 39.1 22.0 Greece
GT GTM 15.8 -90.2 Guatemala
GU GUM 13.4 144.8 Guam
GW GNB 12.0 -15.0 Guinea-Bissau
GY GUY 4.9 -58.9 Guyana
HK HKG 22.3 114.2 Hong Kong
HN HND 15.2 -86.2 Honduras
HR HRV 45.1 15.2 Croatia
HT HTI 19.0 -72.3 Haiti
HU HUN 47.2 19.5 Hungary
ID IDN -2.5 118.0 Indonesia
IE IRL 53.4 -8.2 Ireland
IL ISR 31.0 34.9 Israel
IM IMN 54.2 -4.5 Isle of Man
IN IND 21.0 78.0 India
IO IOT -6.3 71.9 British Indian Ocean Territory
IQ IRQ 33.2 43.7 Iraq
IR IRN 32.4 53.7 Iran
IS ISL 64.9 -19.0 Iceland
IT ITA 42.8 12.6 Italy
JE JEY 49.2 -2.1 Jersey
JM JAM 18.1 -77.3 Jamaica
JO JOR 30.6 36.2 Jordan
JP JPN 36.2 138.3 Japan
KE KEN -0.0 37.9 Kenya
KG KGZ 41.2 74.8 Kyrgyzstan
KH KHM 12.6 105.0 Cambodia
KI KIR 1.9 -157.4 Kiribati
KM COM -11.9 43.9 Comoros
KN KNA 17.3 -62.7 Saint Kitts and Nevis
KP PRK 40.3 127.5 North Korea
KR KOR 36.5 127.9 South Korea
KW KWT 29.3 47.5 Kuwait
KY CYM 19.3 -81.3 Cayman Islands
KZ KAZ 48.0 66.9 Kazakhstan
LA LAO 19.9 102.5 Laos
LB LBN 33.9 35.9 Lebanon
LC LCA 13.9 -61.0 Saint Lucia
LI LIE 47.2 9.6 Liechtenstein
LK LKA 7.9 80.8 Sri Lanka
LR LBR 6.4 -9.4 Liberia
LS LSO -29.6 28.2 Lesotho
LT LTU 55.2 23.9 Lithuania
LU LUX 49.8 6.1 Luxembourg
LV LVA 56.9 24.6 Latvia
LY LBY 26.3 17.2 Libya
MA MAR 31.8 -7.1 Morocco
MC MCO 43.7 7.4 Monaco
MD MDA 47.4 28.4 Moldova
ME MNE 42.7 19.4 Montenegro
MG MDG -18.8 46.9 Madagascar
MH MHL 7.1 171.2 Marshall Islands
MK MKD 41.6 21.7 North Macedonia
ML MLI 17.6 -4.0 Mali
MM MMR 21.9 96.0 Myanmar
MN MNG 46.9 103.8 Mongolia
MO MAC 22.2 113.5 Macao
MP MNP 15.1 145.7 Northern Mariana Islands
MQ MTQ 14.6 -61.0 Martinique
MR MRT 21.0 -10.9 Mauritania
MT MLT 35.9 14.4 Malta
MU MUS -20.3 57.6 Mauritius
MV MDV 3.2 73.2 Maldives
MW MWI -13.3 34.3 Malawi
MX MEX 23.6 -102.5 Mexico
MY MYS 4.2 102.0 Malaysia
MZ MOZ -18.7 35.5 Mozambique
NA NAM -22.9 18.5 Namibia
NC NCL -21.3 165.6 New Caledonia
NE NER 17.6 8.1 Niger
NG NGA 9.1 8.7 Nigeria
NI NIC 12.9 -85.2 Nicaragua
NL NLD 52.1 5.3 Netherlands
NO NOR 61.0 9.0 Norway
NP NPL 28.4 84.1 Nepal
NU NIU -19.1 -169.9 Niue
NZ NZL -41.0 174.0 New Zealand
OM OMN 21.5 55.9 Oman
PA PAN 8.5 -80.8 Panama
PE PER -9.2 -75.0 Peru
PF PYF -17.7 -149.4 French Polynesia
PG PNG -6.3 143.9 Papua New Guinea
PH PHL 12.9 121.8 Philippines
PK PAK 30.4 69.3 Pakistan
PL POL 51.9 19.1 Poland
PM SPM 46.9 -56.3 Saint Pierre and Miquelon
PR PRI 18.2 -66.5 Puerto Rico
PS PSE 31.9 35.2 Palestine
PT PRT 39.4 -8.2 Portugal
PW PLW 7.5 134.6 Palau
PY PRY -23.4 -58.4 Paraguay
QA QAT 25.4 51.2 Qatar
RE REU -21.1 55.5 Reunion
RO ROU 45.9 25.0 Romania
RS SRB 44.0 21.0 Serbia
RU RUS 60.0 90.0 Russia
RW RWA -1.9 29.9 Rwanda
SA SAU 23.9 45.1 Saudi Arabia
SB SLB -9.6 160.2 Solomon Islands
SC SYC -4.7 55.5 Seychelles
SD SDN 15.5 30.2 Sudan
SE SWE 62.0 15.0 Sweden
SG SGP 1.35 103.8 Singapore
SI SVN 46.1 14.9 Slovenia
SK SVK 48.7 19.7 Slovakia
SL SLE 8.5 -11.8 Sierra Leone
SM SMR 43.9 12.5 San Marino
SN SEN 14.5 -14.5 Senegal
SO SOM 5.2 46.2 Somalia
SR SUR 3.9 -56.0 Suriname
ST STP 0.2 6.6 Sao Tome and Principe
SV SLV 13.8 -88.9 El Salvador
SX SXM 18.0 -63.1 Sint Maarten
SY SYR 34.8 39.0 Syria
SZ SWZ -26.5 31.5 Eswatini
TC TCA 21.7 -71.8 Turks and Caicos Islands
TD TCD 15.5 18.7 Chad
TG TGO 8.6 0.8 Togo
TH THA 15.9 101.0 Thailand
TJ TJK 38.9 71.3 Tajikistan
TK TKL -9.2 -171.8 Tokelau
TL TLS -8.9 125.7 Timor-Leste
TM TKM 39.0 59.6 Turkmenistan
TN TUN 33.9 9.5 Tunisia
TO TON -21.2 -175.2 Tonga
TR TUR 39.0 35.2 Turkey
TT TTO 10.7 -61.2 Trinidad and Tobago
TW TWN 23.7 121.0 Taiwan
TZ TZA -6.4 34.9 Tanzania
UA UKR 48.4 31.2 Ukraine
UG UGA 1.4 32.3 Uganda
UM UMI 19.3 166.6 United States Minor Outlying Islands
US USA 39.8 -98.6 United States
UY URY -32.5 -55.8 Uruguay
UZ UZB 41.4 64.6 Uzbekistan
VC VCT 13.2 -61.2 Saint Vincent and the Grenadines
VE VEN 6.4 -66.6 Venezuela
VG VGB 18.4 -64.6 British Virgin Islands
VI VIR 18.3 -64.9 United States Virgin Islands
VN VNM 14.1 108.3 Vietnam
WS WSM -13.8 -172.1 Samoa
YE YEM 15.6 48.5 Yemen
ZA ZAF -30.6 22.9 South Africa
ZM ZMB -13.1 27.8 Zambia
ZW ZWE -19.0 29.2 Zimbabwe
"""

COUNTRIES: dict[str, dict] = {}
ALPHA3: dict[str, str] = {}
for _line in _TABLE.strip().splitlines():
    _a2, _a3, _lat, _lon, _name = _line.split(" ", 4)
    COUNTRIES[_a2] = {"code": _a2, "name": _name, "lat": float(_lat), "lon": float(_lon)}
    ALPHA3[_a3] = _a2

# Two-letter codes that mean one country in the ISO standard and a different one in the older FIPS standard.
# California's file mixes both, so a raw code from this list cannot be placed on a map with confidence.
FIPS_CLASH = {
    "AG", "AS", "AT", "AU", "BA", "BD", "BF", "BG", "BH", "BM", "BN", "BO", "BS", "BY", "CD", "CF", "CG", "CH", "CI",
    "CN", "CW", "DM", "DO", "ES", "GA", "GB", "GE", "GG", "GM", "GN", "GQ", "IS", "KN", "KR", "LI", "LS", "LT", "MA",
    "MC", "MG", "MH", "MN", "MO", "MP", "MU", "NA", "NE", "NG", "NI", "NU", "PA", "PF", "PG", "PM", "PS", "RS", "SB",
    "SC", "SE", "SG", "SN", "ST", "SV", "SZ", "TD", "TK", "TL", "TN", "TO", "TT", "ZA",
}

# United States territories. An owner whose last known address is in one of them is not "in another country", so
# the totals count them in a bucket of their own, apart from both the United States and the countries abroad.
US_TERRITORIES = frozenset({"PR", "GU", "VI", "AS", "MP", "UM"})

# Where the money is held: the centre of California.
ORIGIN = {"code": "US-CA", "name": "California", "lat": 36.8, "lon": -119.4}


# Raw codes that the owner cities under them contradict, each decided by those cities in the file of 4 Nov 2026 (the
# most common cities under the code and how many owner records carry them; no names were looked at). The value is
# the country the cities are in, or None when they lie in several countries, so the code cannot be placed and its
# properties go to the "country codes that cannot be placed" line.
RAW_DECIDED: dict[str, str | None] = {
    "PRK": "KR",   # Incheon, Gyeonggi-do, Daegu, Busan, Suwon: all South Korea (the letters are North Korea's)
    # Californian postcode prefixes and county names written where the country belongs: these owners are at home.
    "939": "US",   # Salinas, Soledad, Greenfield, King City
    "277": "US",   # Porterville, Berkeley, Fullerton, Compton, Los Angeles
    "950": "US",   # Castroville, Hollister
    "934": "US",   # Santa Maria
    "387": "US",   # Stanton, Oxnard
    "SLI": "US",   # El Centro in both records
    # Spellings that are not in either code list, with cities that settle them.
    "TAI": "TW",   # Taipei, New Taipei City
    "JAP": "JP",   # Nagoya, Okinawa, Osaka
    "KUW": "KW",   # Safat
    "SPA": "ES",   # Palma, Palamos
    "UAE": "AE",   # Dubai
    "CDN": "CA",   # Oakville
    "GIN": "PG",   # Lae, Papua, in both records (the letters are Guinea's)
    "COG": "CD",   # Kinshasa in both records (the letters are the Republic of the Congo's)
    # Cities in several countries: these cannot be placed.
    "YUG": None,   # Beograd, Ljubljana, Dubrovnik, Zadar, Skopje, Herceg Novi: the former Yugoslavia
    "SKV": None,   # "Czechoslovakia", Slovakia, Kosice
    "SWZ": None,   # Geneva, Lausanne, Zurich beside Mbabane and Manzini: Switzerland and Eswatini mixed
    "GMB": None,   # Vallendar, Hamburg, Frankfurt, Aachen beside Banjul and Serrekunda: Germany and the Gambia mixed
    "GEO": None,   # Tbilisi and Poti beside Munster, Duesseldorf, Bocholt: Georgia and Germany mixed
    "BIH": None,   # Minsk and Borisov beside Sarajevo, Tesanj, Banja Luka: Belarus and Bosnia mixed
    "SRB": None,   # Belgrade, Nis, Pozarevac beside Moscow, Krasnodar, Vladivostok, Novosibirsk
    "RWA": None,   # Kigali beside Trondheim, Stavanger, Baerum: Rwanda and Norway mixed
    "ATG": None,   # St John's beside Marigot (Saint Martin) and The Valley (Anguilla)
    "TCD": None,   # N'Djamena beside Sangre Grande and Penal in Trinidad
    "MDG": None,   # Antananarivo beside Juiz de Fora in Brazil
    "MLI": None,   # Bamako beside Thyolo (Malawi) and Negeri Sembilan (Malaysia)
    "CAF": None,   # Pinelands, Taipa, Blida: none of them in the Central African Republic
    "NER": None,   # The Hague, Rotterdam, Hilversum beside "Lagos Niger"
    "STP": None,   # no city at all, only a street line of the United States kind
    "FRO": None,   # one record, Capital Federal (Buenos Aires)
    "COM": None,   # one record, Novoivanovskoe with a Russian postcode
    "DJI": None,   # one record, Soeborg in Denmark
    "SPM": None,   # one record, Colon
}

# Single cities that sit under the wrong country. The holder's own software seems to have guessed the country from
# letters in the city line ("BC" read as British Columbia where it is Baja California, "Puerto" as Puerto Rico,
# "Bermuda Dunes" as Bermuda). Each line: the country the code says, how the city line begins, how the postcode
# begins ("" for any), and the country the city is in. Only cities with about a dozen owner records or more under
# that code are listed, each one checked against the postcodes on the same records.
CITY_DECIDED: tuple[tuple[str, str, str, str], ...] = (
    ("CA", "TIJUANA", "", "MX"),          # about 2,100 owner records, postcodes beginning 220 to 224 where one is given
    ("CA", "MEXICALI", "", "MX"),         # about 1,250, postcodes beginning 210 to 213
    ("CA", "ENSENADA", "", "MX"),         # about 320, postcodes beginning 227 to 229
    ("CA", "TECATE", "", "MX"),
    ("CA", "ROSARITO", "", "MX"),
    ("CA", "MEXICO", "", "MX"),
    ("CA", "ONTARIO", "917", "US"),       # Ontario in California, about 1,200 with a postcode beginning 917
    ("CA", "LA CANADA", "", "US"),        # La Canada Flintridge in California, postcodes beginning 910
    ("CA", "PLAYA DEL REY", "", "US"),    # Los Angeles, postcodes beginning 902
    ("CA", "OMAHA NB", "", "US"),         # Nebraska, postcodes beginning 681
    ("PR", "AGOURA", "", "US"),           # Agoura Hills in California, about 420, postcodes beginning 913
    ("PR", "PUERTO VALLARTA", "", "MX"),  # Jalisco, postcodes beginning 482 and 483
    ("BM", "BERMUDA DUNES", "", "US"),    # California, postcodes beginning 922
    ("MX", "TOLUCA LAKE", "", "US"),      # Los Angeles, postcodes beginning 915 and 916
    ("CN", "CHINA LAKE", "", "US"),       # California, postcodes beginning 935
    ("CN", "RIDGECREST", "", "US"),       # California, postcodes beginning 935
    ("CN", "TAICHUNG", "", "TW"),
    ("CN", "TAINAN", "", "TW"),
    ("CN", "HONG KONG", "", "HK"),        # the file gives Hong Kong a code of its own
    ("CN", "LAS CONDES", "", "CL"),       # Santiago
    ("AU", "PORT AU PRINCE", "", "HT"),
    ("AU", "MANAUS", "", "BR"),           # postcodes beginning 690
    ("AS", "AUSTRALIA", "", "AU"),
    ("AS", "SYDNEY", "", "AU"),
    ("DE", "SAN GERMAN", "", "PR"),
    ("DE", "PORTO ALEGRE", "", "BR"),
    ("IE", "BELFAST", "", "GB"),          # postcodes beginning BT
    ("ES", "PORT OF SPAIN", "", "TT"),
    ("BE", "HUNTINGTON BE", "", "US"),    # Huntington Beach in California
    ("RU", "KING OF PRUSSIA", "", "US"),  # Pennsylvania, postcodes beginning 194
    ("SV", "SALVADOR BA", "", "BR"),      # Salvador, Bahia
    ("KE", "KAMAKURA", "", "JP"),         # Kanagawa, postcodes beginning 248
)


def resolve(code: str, trusted: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Turns a register country code into an ISO alpha-2 code, or None when its meaning is not certain.

    `trusted` holds alpha-2 codes the loader has already settled on, which are accepted as they are.
    """
    c = (code or "").strip().upper()
    if c in RAW_DECIDED:
        return RAW_DECIDED[c]
    if c in trusted and c in COUNTRIES:
        return c
    if len(c) == 3 and c in ALPHA3:
        return ALPHA3[c]
    if len(c) == 2 and c in COUNTRIES and c not in FIPS_CLASH:
        return c
    return None
