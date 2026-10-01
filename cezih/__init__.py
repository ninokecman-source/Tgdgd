"""
Spajanje klinike na CEZIH (e-Nalaz / e-Karton) preko FHIR R4 sučelja.

VAŽNO: adrese, nazivi identifikatora i profili u ovom paketu su razumni
zadani odabiri, ne prepisana službena specifikacija. Prije stvarnog slanja
treba ih uskladiti s dokumentacijom koju klinika dobije od CEZIH-a pri
priključenju (vidi cezih/README.md). Sve što ovisi o okruženju nalazi se u
cezih/config.json, a konstante identifikatora na vrhu cezih/nalaz.py.
"""
