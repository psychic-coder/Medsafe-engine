"""Tests for ``medsafe.resolution.normalize``.

# TODO: TestCaseAndWhitespace — case folding, trimming, collapsed internal whitespace
# TODO: TestPunctuationAndUnicode — hyphens, parentheses, unicode/accent normalization
# TODO: TestSaltAndEsterSuffixes — hydrochloride/sodium/hydrate handled consistently
# TODO: TestStrengthExtraction — "500mg", "500 MG", "0.5g" split into value + unit,
#       never silently dropped
# TODO: TestFormExtraction — tablet/cap/syrup/injection tokens split out of the name
# TODO: TestSpellingVariants — British/American variants normalize to the same key
# TODO: TestIdempotence — normalize(normalize(x)) == normalize(x)
# TODO: TestDeterminism — same input, same output across runs and vocabularies
# TODO: TestDoesNotConflateDistinctDrugs — normalization never maps two blocklisted confusables
#       onto the same key (regression guard on the whole policy)
"""
