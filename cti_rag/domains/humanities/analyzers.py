from dataclasses import dataclass

@dataclass(frozen=True)
class AnalyzerProfile:
    language:str
    analyzer_version:str|None
    supported:bool
    reason:str=""
    capabilities:tuple[str,...]=()

_PROFILES={
 "en":AnalyzerProfile("en","unicode61/1",True,capabilities=("unicode_tokenization","diacritic_folding")),
 "la":AnalyzerProfile("la","unicode61/1",True,"tokenization only; no Latin lemmatization",("unicode_tokenization",)),
 "fr":AnalyzerProfile("fr","unicode61/1",True,"tokenization only; no French stemming",("unicode_tokenization","diacritic_folding")),
 "grc":AnalyzerProfile("grc",None,False,"Ancient Greek analyzer/lemmatizer is not configured in the validated SQLite FTS5 profile"),
 "ar":AnalyzerProfile("ar",None,False,"Arabic analyzer is not configured in the validated SQLite FTS5 profile"),
}
def analyzer_profile(language:str)->AnalyzerProfile:
    return _PROFILES.get(language,AnalyzerProfile(language,None,False,"language/analyzer combination is not registered"))
def supported_analyzer_languages():
    return tuple(sorted(k for k,v in _PROFILES.items() if v.supported))
