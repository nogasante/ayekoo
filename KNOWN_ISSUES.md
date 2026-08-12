# Known issues

Recorded rather than hidden. Each entry has a reproduction so it can be picked
up and worked on directly.

## 1. RESOLVED — symptom questions are now answered by quotation

Was: "my chickens are dying suddenly" was declined even though the corpus
states that sudden high mortality is the diagnostic sign of Newcastle disease.

Two things were wrong, and they had to be fixed in order.

**Retrieval.** The passage naming ND ranked 32nd by similarity and 428th by
BM25 for that phrasing. Fixed by adding a Ghana-specific poultry source (FAO's
Ghana poultry sector review), symptom vocabulary to the alias map ("green
droppings" -> "greenish diarrhoea", "cannot walk" -> "paralysis"), capping
chunks per source, and widening the fusion window from 20 to 80.

**Generation.** Even with the right passages retrieved, the model refused. The
refusal clause in the system prompt was the trigger: removing it made the model
answer, but it then merged Newcastle disease with fowl cholera and attributed
Pasteurella multocida to the same picture. A third framing produced "coat
dragging on the ground", a garbled reading of drooping wings.

All three outcomes are unacceptable for animal health advice, so symptom
questions no longer go through the model at all. `extract_symptoms` quotes the
signs the sources record, names the diseases the sources name, and says plainly
that it is not diagnosing and that a veterinary or extension officer should
look at the animals. Same principle as planting dates and prices: where
precision matters, quote rather than paraphrase.

The cassava case is the clearest illustration of why this is better than a
summary — the quoted passage carries the source's own warning: "You should not
confuse chlorotic spots caused by the pest with the chlorotic patches of
cassava mosaic disease."

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
