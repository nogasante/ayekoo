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

## 2. RESOLVED — regions and towns now resolve to agro-ecological zones

Was: no source in this corpus stated which region sat in which zone, so a
question naming a town got the whole planting calendar and a note that the zone
was unknown.

Resolved by the Ghana Meteorological Agency's *Weather and Climate Manual for
Agriculture* (2022), which states the mapping directly. "When should I plant
maize in Tamale?" now returns End of May to early July.

Three things are handled deliberately rather than smoothed over:

- **Regions spanning zones return all of them.** Ashanti lies across the
  Transition and Deciduous Forest zones, so a Kumasi question shows both
  windows instead of picking the larger one.
- **The town-to-region step is disclosed as unsourced.** No document here says
  Tamale is in the Northern Region. The answer says so: that step is ours, the
  region-to-zone step is GMet's.
- **GMet and FAO disagree about the Coastal Savannah** — one rainy season and
  600mm versus two seasons and 800mm. Both are reproduced without
  reconciliation.

GMet uses the pre-2018 ten-region names, which is recorded against every entry
touching the former Brong Ahafo.

## 3. Cassava and plantain lean on West African rather than Ghanaian sources

MoFA has never published cassava or plantain production guides. Both crops rest
mainly on IITA material, which is good agronomy but Nigeria-centred. Every such
source is tagged `ghana_specific: false` and labelled in answers, so nothing is
misrepresented, but the localisation claim is weaker for these two crops than
for maize, cocoa, tomato or rice.

## 4. RESOLVED — the corpus was recommending pesticides banned in Ghana

Cross-checking every document against Ghana EPA's *Revised Register of
Pesticides* (December 2023) found two banned substances being recommended by
sources in this corpus:

- **chlordecone** — IITA plantain manual (1990), in a dosage table, 1 gram per
  plant, for banana weevil control
- **methyl bromide** — FAO yam post-harvest guide, for fumigation

The same IITA table also lists **HCH**, likewise banned. Chlordecone is a
persistent organic pollutant banned under the Stockholm Convention; it caused a
long-running public health disaster in the French Antilles.

Neither source is wrong about what was recommended when it was written. They are
older than the regulations. This is the specific hazard of building a corpus on
durable agronomy: the agronomy stays true, chemical registrations do not, and no
similarity score can tell the difference.

`ayekoo/banned.py` now drops any retrieved passage naming a substance on the EPA
banned list, before it reaches either the model or the extractive paths, and
attaches a warning naming the substance and pointing at the current register.

**Worth knowing:** this was found by an explicit regulatory cross-check, not by
retrieval testing or by reading answers. Nothing about the passage looks wrong
in isolation — it is a well-formed dosage table from a reputable institution.
Any corpus of agricultural documents older than about five years should be
checked the same way.

## 5. OPEN — categorical claims are not verified, only numbers and months

Asked "what is Obatanpa", the system answered "Obatanpa is a hybrid maize
variety released in Ghana". No document in this corpus calls Obatanpa a hybrid;
the model inferred it. (Obatanpa is in fact an open-pollinated variety, so the
inference is also wrong.)

`verify.py` did not catch it because it checks numbers and months. A claim of
category — hybrid versus open-pollinated, resistant versus susceptible, annual
versus perennial — passes untouched.

This is the same class of failure as the corrupted planting windows, and it has
the same answer: where a distinction matters, quote rather than paraphrase.
Variety questions should probably join dates, prices and symptoms on the
extractive path.

Not fixed because it was found late and the fix is not a one-liner: the variety
catalogue's entries are structured records rather than prose sentences, so
quoting them well needs its own extraction. Recorded rather than rushed.

**Deliberate consequence:** neither submitted test prompt asks a system to
classify a variety. `tp_001` asks which varieties are recommended for a zone,
which is answered by quoting MoFA's list verbatim.

## 6. OPEN — vegetables have vocabulary but no content

Okra, garden egg, onion and pepper now have local-language aliases pointing at
them — `fetri`, `nkruma`, `nyaadewa`, `ntrowa`, `mako` — and there is nothing
behind those words. Measured after adding them:

    fetri pests                       0.69   weak
    nkruma farming                    0.71   weak
    nyaadewa farming                  0.68   weak
    akyimkyimakyimkyim on my onions   0.61   refused

The last one is the clearest case. Ghanaian field surveys record
*akyimkyimakyimkyim* as the farmer name for onion leaf-twisting disease in
Fanteakwa and Kwahu South. The alias resolves it to "twisting" and "leaf curl",
and the corpus contains two mentions of "twisting" in any context. There is
nothing to retrieve.

**The lesson is worth keeping: an alias bridges vocabulary to content, it
cannot create content.** Adding these words made the gap visible — a farmer
asking about okra is now routed accurately to nothing — which is more honest
than the previous behaviour of matching a poultry manual, but it is not a fix.

Ghana grows a great deal of pepper, okra, garden egg and onion, and MoFA has
published a production guide for none of them. The tomato guide is the only
vegetable source in the corpus. Closing this needs a real vegetable production
manual, Ghanaian or West African; searches of MoFA, CSIR, CGSpace and FAO have
not turned one up.

### Update — two vegetable manuals tried, gap NOT closed

Both candidates failed, in different and instructive ways.

**WorldVeg, *A Practical Training Guide for Vegetable Production* (2025).** A
scanned PDF. It yielded 4,148 characters across 50 pages — 83 per page — all of
it the title page and author list, with no mention of pepper, onion, garden egg,
spacing or nursery. It cleared the pipeline's 2,000-character floor on front
matter alone and would have entered the corpus looking like vegetable coverage
while holding none. `fetch_sources.py` now checks characters per page as well as
total, which rejects it.

**CGIAR, *Postharvest Handling and Diversified Vegetable Use* (2024).** Real
text, 45,421 characters, but it is about postharvest handling generally: 0
mentions of okra, 0 of pepper, 0 of garden egg, 1 of onion, 8 of tomato. Kept,
but re-tagged `crops: [tomato]` after reading it. The original tag listed five
vegetables and would have made subject routing lift it for okra questions it
cannot answer. **A source claiming coverage it does not have is worse than no
source** — it converts an honest refusal into a confident irrelevance.

So vegetables remain open. Searched without success: MoFA, CSIR, CGSpace, FAO,
the World Vegetable Center, GhanaVeg. Ghana grows a great deal of pepper, okra,
garden egg and onion, and there appears to be no digitised production manual for
any of them, Ghanaian or West African, that is not a scan.
