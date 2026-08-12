# Known issues

Recorded rather than hidden. Each entry has a reproduction so it can be picked
up and worked on directly.

## 1. "My chickens are dying suddenly" is declined, though the corpus answers it

**Reproduce**

    python -m ayekoo.ask "my chickens are dying suddenly, what could it be?"

Returns "My sources do not cover this."

**Why it is wrong**

The corpus contains the answer. `fao-smallscale-poultry` states: *"The most
obvious diagnostic sign of ND is very sudden, very high mortality, often with
few symptoms"*, and `fao-newcastle-village-poultry` is a whole document about
controlling it. Newcastle disease is the biggest killer of village poultry in
West Africa, so this is a question farmers really ask.

**What is actually happening**

The passage holding the answer (chunk 2416) ranks 32nd by dense similarity and
428th by BM25 for this phrasing. It loses rank fusion to general poultry
husbandry pages that match "chickens" more strongly. The model then sees four
passages about disease diagnosis in general and correctly declines rather than
invent — the refusal path working as designed, on a retrieval failure.

**Tried, did not fix it**

- subject routing (poultry sources are lifted, but they all are)
- capping chunks per source, so one manual cannot monopolise the results
- alias expansion: "dying suddenly" -> sudden, mortality, newcastle
- widening the fusion candidate window from 20 to 80
- raising top_k from 4 to 6 and 8

**Worth trying next**

- A symptom-to-disease index built from the disease sections specifically,
  rather than relying on general similarity across whole manuals.
- Query rewriting: turn a symptom description into the clinical vocabulary the
  manuals use before retrieval, rather than only appending alias terms.
- Weighting the dense score by absolute similarity rather than rank alone, so a
  strong-but-lower-ranked match can beat several weak ones.

## 2. Town names do not resolve to agro-ecological zones

A farmer says "Tamale", not "Guinea Savannah Zone". No document in this corpus
states the full region-to-zone mapping, and it is deliberately not filled in
from general knowledge. Ayekoo says the zone is unknown and shows the whole
planting calendar instead. Only "Upper East -> Sudan Savannah" is mapped,
because that is the one such statement a source makes.

Closing this needs a citable Ghanaian source listing regions by zone.

## 3. Cassava and plantain lean on West African rather than Ghanaian sources

MoFA has never published cassava or plantain production guides. Both crops rest
mainly on IITA material, which is good agronomy but Nigeria-centred. Every such
source is tagged `ghana_specific: false` and labelled in answers, so nothing is
misrepresented, but the localisation claim is weaker for these two crops than
for maize, cocoa, tomato or rice.
