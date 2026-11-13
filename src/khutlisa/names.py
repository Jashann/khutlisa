"""Name handling: how one person's name shows up differently across borders and decades."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from itertools import permutations

_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_SPACE = re.compile(r"\s+")
# Words that carry no identity in an owner field.
NOISE = {"MR", "MRS", "MS", "DR", "JR", "SR", "II", "III", "IV", "EST", "ESTATE", "OF", "THE", "AND", "OR",
         "TTEE", "TRUSTEE", "TRUST", "CUST", "UTMA", "JT", "TEN", "DEC", "DECD", "DECEASED", "FBO", "ETAL"}
# Particles that are written joined or apart depending on the clerk.
PARTICLES = {"DE", "DEL", "DELA", "DELOS", "LA", "LOS", "LAS", "VAN", "VON", "DER", "DEN", "DI", "DA", "DOS", "BIN",
             "BINTI", "AL", "EL", "ST", "SAN", "SANTA", "MC", "MAC", "O"}
ORG_WORDS = {"INC", "LLC", "LLP", "LP", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "BANK",
             "UNIVERSITY", "COLLEGE", "CITY", "COUNTY", "STATE", "DEPT", "DEPARTMENT", "ASSOCIATION", "ASSN",
             "FOUNDATION", "CHURCH", "HOSPITAL", "SCHOOL", "DISTRICT", "GROUP", "PARTNERS", "SERVICES", "SA", "AG",
             "GMBH", "PLC", "PTY", "KK", "SDN", "BHD", "NV", "BV", "SPA", "SRL", "FUND", "INSURANCE", "AUTHORITY"}
# Common romanisation swaps (applied as alternatives, never as replacements).
ROMAN = [("PH", "F"), ("V", "B"), ("Z", "S"), ("Y", "I"), ("CK", "K"), ("C", "K"), ("OU", "U"), ("OO", "U"),
         ("EE", "I"), ("KH", "H"), ("ZH", "J"), ("X", "SH"), ("Q", "CH"), ("TS", "C"), ("W", "V"), ("H", "")]


def normalise(text: str) -> str:
    """Upper-case ASCII with single spaces: 'Núñez-O'Brien, María' -> 'NUNEZ OBRIEN MARIA'."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).upper().replace("'", "").replace("’", "")
    return _SPACE.sub(" ", _PUNCT.sub(" ", t)).strip()


def tokens(text: str) -> list[str]:
    return [t for t in normalise(text).split() if t not in NOISE]


def is_organisation(name: str) -> bool:
    return any(t in ORG_WORDS for t in normalise(name).split())


# Particles a clerk may join to the family name ('DELACRUZ', 'MCDONALD'). Longest first.
JOINED_PARTICLES = [("DELOS", ["DE LOS", "DELOS"]), ("DELAS", ["DE LAS", "DELAS"]), ("DELA", ["DE LA", "DELA"]),
                    ("DEL", ["DEL"]), ("DE", ["DE"]), ("MAC", ["MAC"]), ("MC", ["MC"]), ("VANDER", ["VAN DER", "VANDER"]),
                    ("VANDEN", ["VAN DEN", "VANDEN"]), ("VAN", ["VAN"]), ("VON", ["VON"])]
# The particles whose bearer is also met under the bare name ('CRUZ' for 'DELACRUZ', 'LEON' for 'DE LEON').
DROPPABLE = ["DELOS", "DELAS", "DELA", "DEL", "DE"]
_PARTICLE_PAIRS = {"DELA": ["DE", "LA"], "DELOS": ["DE", "LOS"], "DELAS": ["DE", "LAS"]}


def split_joined(token: str, limit: int = 2) -> list[str]:
    """Ways a joined family name may be written apart: 'DELACRUZ' -> ['DE LA CRUZ', 'DELA CRUZ'],
    'MCDONALD' -> ['MC DONALD']. The rest after the particle must be three letters or more."""
    out: list[str] = []
    for prefix, spellings in JOINED_PARTICLES:
        rest = token[len(prefix):]
        if token.startswith(prefix) and len(rest) >= 3:
            for sp in spellings:
                if f"{sp} {rest}" not in out:
                    out.append(f"{sp} {rest}")
    return out[:limit]


def particle_spellings(toks: list[str]) -> set[str]:
    """Other ways to space the particles of one family name. ['DE', 'LA', 'CRUZ'] also gives 'DELA CRUZ';
    ['DELA', 'CRUZ'] also gives 'DE LA CRUZ'; ['DELACRUZ'] gives both."""
    if len(toks) == 1:
        return set(split_joined(toks[0]))
    out: set[str] = set()
    merged: list[str] = []
    i = 0
    while i < len(toks):                      # DE LA -> DELA
        pair = toks[i] + toks[i + 1] if i + 1 < len(toks) else ""
        if pair in _PARTICLE_PAIRS:
            merged.append(pair); i += 2
        else:
            merged.append(toks[i]); i += 1
    apart = [x for t in toks for x in _PARTICLE_PAIRS.get(t, [t])]     # DELA -> DE LA
    for alt in (merged, apart):
        if alt != toks:
            out.add(" ".join(alt))
    return out


def droppable_rest(token: str) -> str:
    """'CRUZ' for 'DELACRUZ' and 'LEON' for 'DELEON': the family name without a joined DE particle, or ''."""
    for prefix in DROPPABLE:
        if token.startswith(prefix) and len(token) - len(prefix) >= 4:
            return token[len(prefix):]
    return ""


# Familiar forms of given names in English, Spanish and Filipino use. Each line is one formal name and the short
# forms people answer to. A short form may stand under more than one formal name (TONY, LITA, NENA).
_NICKNAME_LINES = """
WILLIAM: BILL BILLY WILL
ROBERT: BOB BOBBY ROB
RICHARD: RICK DICK
JAMES: JIM JIMMY
JOHN: JACK JOHNNY
JOSEPH: JOE
MICHAEL: MIKE
THOMAS: TOM TOMMY
CHARLES: CHARLIE CHUCK
EDWARD: ED EDDIE TED
DANIEL: DAN DANNY
DAVID: DAVE
STEPHEN: STEVE
STEVEN: STEVE
CHRISTOPHER: CHRIS
MATTHEW: MATT
ANTHONY: TONY
ANDREW: ANDY
BENJAMIN: BEN
SAMUEL: SAM
ALEXANDER: ALEX
NICHOLAS: NICK
PATRICK: PAT
PETER: PETE
KENNETH: KEN
LAWRENCE: LARRY
RONALD: RON
DONALD: DON
TIMOTHY: TIM
FREDERICK: FRED
HENRY: HANK
GERALD: JERRY
RAYMOND: RAY
MARGARET: PEGGY MEG MAGGIE
ELIZABETH: BETTY BETH LIZ
KATHERINE: KATE KATHY
CATHERINE: CATHY KATE
PATRICIA: PAT PATTY
JENNIFER: JEN JENNY
BARBARA: BARB
DOROTHY: DOT DOTTIE
SUSAN: SUE
DEBORAH: DEBBIE
REBECCA: BECKY
VICTORIA: VICKY
CHRISTINE: CHRIS TINA
JACQUELINE: JACKIE
CYNTHIA: CINDY
PAMELA: PAM
JUDITH: JUDY
KIMBERLY: KIM
JOSE: PEPE
FRANCISCO: PACO PANCHO CHITO KIKO
ANTONIO: TONY TONO
IGNACIO: NACHO
GUILLERMO: MEMO
JESUS: CHUY
ENRIQUE: QUIQUE
EDUARDO: LALO
ALBERTO: BETO
ROBERTO: BETO
MANUEL: MANNY MANOLO
RAFAEL: RAFA
SALVADOR: CHAVA
LUIS: LUCHO
FERNANDO: NANDO
RODOLFO: RUDY
GUADALUPE: LUPE LUPITA
DOLORES: LOLA
CONCEPCION: CONCHA CONNIE
ROSARIO: CHARO
MERCEDES: MECHE
JOSEFINA: PEPITA JOSIE
FRANCISCA: PAQUITA
TERESA: TERE TESS
MAGDALENA: NENA LENA
ELENA: NENA
ISABEL: CHABELA
GRACIELA: CHELA
CONSUELO: CHELO
BEATRIZ: BETTY BEA
MARIA: MARI
JUNIOR: JUN
JOSELITO: LITO
ANGELITO: LITO
EMMANUEL: MANNY
CORAZON: CORA CORY
REMEDIOS: REMY
TERESITA: TESSIE TESS
""".strip().splitlines()


def _nickname_table() -> dict[str, frozenset[str]]:
    table: dict[str, set[str]] = {}
    for line in _NICKNAME_LINES:
        formal, short = line.split(":")
        group = {normalise(formal)} | {normalise(w) for w in short.split()}
        for name in group:
            table.setdefault(name, set()).update(group - {name})
    return {k: frozenset(v) for k, v in table.items()}


NICKNAMES = _nickname_table()


def nickname_forms(token: str) -> frozenset[str]:
    """Other given names the same person may be recorded under: BILL for WILLIAM, WILLIAM and WILL for BILL."""
    return NICKNAMES.get(token, frozenset())


def near_spelling(typed: str, written: str) -> bool:
    """True when the two differ by exactly one letter (changed, dropped or added), the longer has four letters or
    more and the shorter three or more. JUAN and JUANA are near spellings, which is why a near spelling is never
    counted as a full match."""
    short, long_ = sorted((typed, written), key=len)
    if typed == written or len(long_) < 4 or len(short) < 3 or len(long_) - len(short) > 1:
        return False
    if len(short) == len(long_):
        return sum(a != b for a, b in zip(typed, written)) == 1
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def near_spelling_pattern(typed: str) -> list[str]:
    """Regular-expression pieces that match every near spelling of one typed name. The SQL twin of near_spelling."""
    out = []
    if len(typed) >= 4:
        for i in range(len(typed)):
            out.append(typed[:i] + "[A-Z]" + typed[i + 1:])       # one letter changed
            out.append(typed[:i] + typed[i + 1:])                 # one letter added by the typist
    if len(typed) >= 3:
        for i in range(len(typed) + 1):
            out.append(typed[:i] + "[A-Z]" + typed[i:])           # one letter dropped by the typist
    return list(dict.fromkeys(out))


@dataclass
class Person:
    """Everything a claimant has ever been called."""
    given: list[str]                      # given names in any order of use
    family: list[str]                     # every family name used: birth, married, both halves of a double surname
    aliases: list[str] = field(default_factory=list)   # full strings exactly as once written on a document

    def family_keys(self) -> set[str]:
        """Family-name strings to search the registers for, including joined and split particles."""
        keys: set[str] = set()
        for f in self.family:
            toks = tokens(f)
            if not toks:
                continue
            keys.add(" ".join(toks))
            keys.add("".join(toks))
            keys.update(particle_spellings(toks))
            core = [t for t in toks if t not in PARTICLES]
            if core and (core[-1] not in ORG_WORDS or len(toks) == 1):
                keys.add(core[-1])
        for a in self.aliases:
            toks = tokens(a)
            if toks:
                keys.add(toks[-1]); keys.add(toks[0])
        return {k for k in keys if len(k) >= 2}

    def family_wholes(self) -> set[str]:
        """Each family name as one joined word ('DE LA CRUZ' and 'DELA CRUZ' are both 'DELACRUZ'), plus the first and
        last word of every alias."""
        out = {"".join(tokens(f)) for f in self.family}
        for a in self.aliases:
            toks = tokens(a)
            if toks:
                out.update((toks[0], toks[-1]))
        return {w for w in out if len(w) >= 2}

    def family_cores(self) -> set[str]:
        """The main word of a family name that was typed with a separate particle: 'CRUZ' for 'De la Cruz'."""
        out = set()
        for f in self.family:
            toks = tokens(f)
            core = [t for t in toks if t not in PARTICLES]
            if core and len(core) < len(toks) and core[-1] not in ORG_WORDS:
                out.add(core[-1])
        return {c for c in out if len(c) >= 2}

    def given_keys(self) -> set[str]:
        out: set[str] = set()
        for g in self.given:
            out.update(tokens(g))
        return out


def romanisations(token: str, limit: int = 12) -> set[str]:
    """Plausible respellings of one name token. Used only to widen the search, then scored."""
    seen = {token}
    frontier = [token]
    for a, b in ROMAN:
        nxt = []
        for t in frontier:
            for x, y in ((a, b), (b, a)):
                if x and x in t:
                    v = t.replace(x, y, 1)
                    if len(v) >= 2 and v not in seen:
                        seen.add(v); nxt.append(v)
        frontier += nxt
        if len(seen) >= limit:
            break
    return set(list(seen)[:limit])


def orderings(person: Person, cap: int = 24) -> list[str]:
    """Full-name strings in the orders registers use: FAMILY GIVEN, GIVEN FAMILY, with and without middle names."""
    g = sorted(person.given_keys())
    out: list[str] = []
    for fam in sorted(person.family_keys()):
        for n in range(1, min(len(g), 2) + 1):
            for combo in permutations(g, n):
                out.append(f"{fam} {' '.join(combo)}")
                out.append(f"{' '.join(combo)} {fam}")
    seen: list[str] = []
    for o in out:
        if o not in seen:
            seen.append(o)
    return seen[:cap]


# The same steps are run in SQL when the registers are loaded (see registers.PHON_SQL). Keep the two in step.
_PHON_STEPS = [("PH", "F"), ("CK", "K"), ("KH", "K"), ("GH", "G"), ("SCH", "S"), ("SH", "S"), ("CH", "S"),
               ("TS", "S"), ("TZ", "S"), ("ZH", "S"), ("Q", "K"), ("C", "K"), ("X", "S"), ("Z", "S"), ("J", "S"),
               ("V", "B"), ("W", "B"), ("Y", "I"), ("D", "T"), ("G", "K"), ("M", "N"), ("H", "")]


_PHON_LETTERS = "BFKLNPRSTAEIOU"


def phonetic(token: str) -> str:
    """A rough said-aloud key: 'VILLANUEVA' and 'BILLANUEBA' share one, so do 'ESTEPHANO' and 'ESTEFANO'."""
    t = re.sub(r"[^A-Z]", "", normalise(token))
    if not t:
        return ""
    for a, b in _PHON_STEPS:
        t = t.replace(a, b)
    t = t[:1] + re.sub(r"[AEIOU]", "", t[1:])
    for _ in range(2):          # collapse doubled letters, the same way the SQL twin does
        for c in _PHON_LETTERS:
            t = t.replace(c + c, c)
    return t
