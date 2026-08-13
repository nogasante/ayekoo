# Ayekoo — Technical Report

**An offline farming assistant for Ghanaian farmers, running on an 8 GB laptop.**

Africa Deep Tech Challenge 2026 · Laptop LLM track · domain: `agriculture`
Team `ayekoo` · Nana Opoku Gyamfi Asante · [github.com/nogasante/ayekoo](https://github.com/nogasante/ayekoo)

---

## 1. The problem

Agricultural extension officers in Ghana are spread thin. The farmers who most need advice are the ones with the least connectivity and the cheapest hardware — and every AI farming tool I looked at assumes a data plan, a subscription, and a cloud API. That means it is not there at the moment the question is actually asked, standing in a field.

*Ayekoo* is what you say to someone doing hard work — the greeting a farmer hears coming back from the farm. That is who this is for, and the name is the posture: respect first.

The target user is a smallholder in Ghana asking practical questions. When do I plant maize here? What is eating my cassava? What is maize worth this year? My chickens are dying — what is it?

## 2. The core design decision

**The model is not the source of truth. The corpus is.**

A 0.63B model has no reliable Ghanaian agricultural knowledge in its weights. Asked which maize varieties are released in Ghana, the bare model invented an institution ("Ghana Agricultural Research Organization"), invented two varieties ("Ghana 12", "Ghana 13"), and described a "12-month maize variety". Asked the seed rate per acre for open-pollinated maize, it answered "1.5–2.0 kg per hectare" — wrong by an order of magnitude, and confidently phrased.

So the model never answers from its own knowledge. It reads retrieved passages from a curated corpus of Ghanaian agricultural documents and says what they contain. On the same seed-rate question, Ayekoo answers **9 kg/acre for OPVs and 10 kg/acre for hybrid maize** — the figure MoFA actually publishes.

This is what makes the cross-disciplinary pairing load-bearing rather than cosmetic: remove the corpus and the system stops being useful at all.

## 3. The corpus

49 documents, 5.4 MB of extracted text, 8,535 indexed chunks. Every document is recorded in `corpus/sources.yaml` with its publisher, year, URL, and the attribution string that travels with every chunk derived from it.

Sources are government and institutional only — MoFA/DAES production guides, the NVRRC national crop variety catalogue, MoFA/SRID *Agriculture in Ghana: Facts & Figures 2024*, the CRIG/COCOBOD cocoa extension manual, FAO and CGIAR/IITA manuals. No blogs, no forums, no video transcripts.

Coverage matches the four sub-domains the challenge defines for agriculture:

| Sub-domain | Coverage |
|---|---|
| Crop | maize, cassava, yam, cocoa, tomato, plantain, rice — each with ≥3 Ghana-specific sources |
| Livestock | poultry, Newcastle disease, sheep and goats, cattle — including FAO's Ghana poultry sector review |
| Weather | GMet's climate manual, rainfall onset and growing-season length by zone |
| Market advisory | 2024 wholesale prices GH₵/tonne for ten crops, plus 2025 quarterly reports |

Every source carries a `ghana_specific` flag. The IITA and FAO manuals are good agronomy but West African or continental in scope, and are labelled as such in answers — where a Ghanaian and a regional source both match, the Ghanaian one is preferred. Stale content carries explicit never-quote caveats: the 2005 FAO fertilizer report's *rates* are still sound, but its prices are in pre-redenomination cedis and must never be surfaced.

## 4. Retrieval

Hybrid: dense embeddings (bge-small-en-v1.5, f16) fused with BM25 by reciprocal rank.

Dense retrieval matches how a farmer phrases a question against how a manual writes it. BM25 catches what embeddings blur — exact strings like `Obatanpa`, `NPK 15-15-15`, `75cm`. Agronomy answers live or die on those, so a purely semantic index would have been the wrong choice.

Three retrieval decisions came out of measured failures rather than theory:

**Compound tokens are split.** The MoFA guide states "Plant 9kg/acre for OPV's". A question about seed rate per acre did not retrieve it, because `9kg/acre` was a single token with nothing in common with `acre`. Tokens now emit their parts as well; that chunk went from unretrieved to rank 1.

**Front matter is filtered.** A question about maize varieties retrieved the variety catalogue's table of contents — dense with exactly the right words, attached to page numbers instead of facts. 190 such chunks were removed.

**Retrieval is routed by subject.** "My goat is sick" returned four chunks from the village chicken manual and no goat content, because this corpus holds roughly ten times more poultry text than goat text and rank fusion rewards a document that places mid-rank in both rankers over one that ranks first in only one. Questions naming an animal or crop now lift sources about that subject and demote sources about a different one.

A 148-entry alias map bridges farmer vocabulary to document vocabulary. The mismatch is measurable: `capsid` appears 5 times in this corpus and `mirid` 41; `army worm` once and `armyworm` twelve times. It carries local crop names (*bankye*, *aburoo*, *nkruma*, *nyaadewa*), local disease names recorded in Ghanaian field surveys (*akyimkyimakyimkyim* for onion leaf-twisting disease, *kokoo kokoram* for cocoa stem canker), the way farmers describe symptoms ("leaves turn yellow", "centre shoot dead", "holes in grain"), and Ghanaian Pidgin constructions ("my maize dey yellow", "pest don finish my pepper").

Every alias target is asserted by a test to occur in the corpus, so the map cannot drift into invented terminology — a check that caught two of my own inventions. The map also has a hard limit worth stating: it bridges vocabulary to content and cannot create content. Adding *fetri* and *nkruma* for okra routes an okra question accurately to nothing, because no source in this corpus covers okra.

## 5. Refusing, and quoting

Two safeguards matter more than usual here, because a wrong answer to a farmer is worse than no answer.

**Refusal is gated on absolute similarity, not rank.** An earlier version gated on the fused rank score, under which *"What is the capital city of Mongolia?"* scored **higher** than a real maize question — rank tells you which chunk matched best, never whether anything matched at all. Cosine separates cleanly: in-scope questions score 0.75–0.84, out-of-scope 0.51–0.59. Below 0.65 Ayekoo says "My sources do not cover this" and never calls the model.

**Planting dates are quoted, not paraphrased.** Three times running, the model corrupted a planting window while getting everything else right — most instructively, turning MoFA's *"End of May to early July"* into *"early May to end of July"*, widening the window by three weeks at each end. Retrieval was correct, the chunk was correct, the months were correct. No verifier that checks months or numbers can catch that, because every element was legitimately present.

The fix was not more prompt engineering. A planting window is a quotation, not a summary. Calendar questions now return the source sentences verbatim from restructured tables, and the answer says so. Everything else still goes through the model, where paraphrase earns its place.

`ayekoo/verify.py` checks that every number and month in a generated answer appears in the passages it came from, and that a month is associated with the zone the question asked about — not merely present somewhere.

**Banned pesticides are blocked outright.** Cross-checking the corpus against Ghana EPA's *Revised Register of Pesticides* (December 2023) found two substances banned in Ghana being recommended by our own sources: **chlordecone**, with a dose, in IITA's 1990 plantain manual, and **methyl bromide** for yam fumigation in FAO's post-harvest guide. The same table lists HCH, also banned.

Neither document is wrong — both are older than the regulations. That is the specific hazard of a corpus built on durable agronomy: the agronomy lasts, the chemical registrations do not, and nothing in a similarity score can tell the difference. `ayekoo/banned.py` drops any passage naming a substance on the EPA banned list before it reaches the model or the extractive paths, and the answer says the substance is banned and points to the current register.

This is the clearest argument for provenance discipline in the whole system. A corpus assembled from reputable institutional sources still contained advice that could have harmed a farmer, and only an explicit regulatory cross-check surfaced it.

## 6. Constraints that shaped this

**8 GB, no GPU, no network.** This drove the choice of a 0.63B model at Q4_K_M and a 67 MB embedding model. Both run through llama.cpp; there is deliberately no second inference stack, no torch, no sentence-transformers. That keeps the "llama.cpp only" rule unambiguous and avoids a multi-gigabyte install on a machine that does not have the room.

**PDF tables do not survive extraction.** The highest-stakes content in this corpus — planting calendars — arrives as interleaved fragments with dates detached from the zones they belong to. Three documents were restructured by hand from tables already in the corpus, marked `derived: true`, with every line checkable against the source PDF.

**Connectivity is a development constraint too.** `iita.org` is unreachable from Ghana on this connection, which initially left plantain with no source at all; CGSpace mirrors the same publications and works. A 469 MB download that silently truncated at 343 MB is why `download_model.sh` verifies size and SHA256 before promoting a file into place.

## 7. Benchmarks

Measured on the development laptop (Intel i5-8265U, 4 threads, 8 GB RAM, Windows 11), idle, with cooldowns between runs.

Machine load matters more than anything in the code, and it is worth stating how much. The same build, same model, same corpus, measured three times:

| Machine state | Throughput |
|---|---|
| Saturated — 255 MB free RAM, swapping | 2.69 tok/s |
| Editor and browser open | 5.88 tok/s |
| **Idle** | **9.77 tok/s** |

Peak RSS barely moved across all three, which is the point: the memory figure is a property of the system, the throughput figure is a property of the machine it is asked to share.

| Metric | Value |
|---|---|
| Peak RSS, full stack loaded (index + embedding model + generation model, one answer) | **331 MB** |
| Peak RSS, profiler measurement | 544.65 MB |
| Efficiency score, `100 × (7 GB − peak) / 7 GB` | **92.4** (from the profiler's 544.65 MB) |
| Throughput | **9.77 tok/s** |
| Model parameters, verified from GGUF header | 630,167,424 |
| Thermal throttling | none — `throttled: false` |

The full retrieval stack costs about 145 MB on top of the models — 8,535 chunks, their vectors, and the BM25 index. Retrieval is not the memory problem it is sometimes assumed to be at this scale.

Verified end-to-end on Ubuntu 24.04 (2 cores, 3.8 GB RAM): `download_model.sh` fetches and checksums both models in 38 s, retrieval reproduces the same scores as on Windows to four decimal places, and a full answer takes 26 s cold on two cores with nothing installed but `pip install -r requirements.txt`.

## 8. How long the facts stay true

An offline system trades freshness for availability. That is the deliberate
bargain, not an oversight: a farmer with no data plan gets a correct planting
window today rather than a live price they can never load. What the design owes
in return is honesty about how old each fact is.

Facts in this corpus have very different shelf lives.

**Effectively permanent.** Planting windows, plant spacings, seed rates,
fertilizer rates, disease symptoms, the rainfall pattern of each agro-ecological
zone. MoFA's maize calendar will read the same in ten years. This is most of the
corpus, and it is why an offline agricultural assistant is viable at all.

**Slowly drifting.** Released variety lists — the national catalogue here is the
2019 edition, and CSIR-CRI has released hybrid maize and yellow-fleshed cassava
varieties since. Recommended chemicals, where registration status changes; the
1992 yam disease guide is marked never-quote for pesticides for exactly this
reason.

**Perishable.** Prices. The most recent official annual figures are 2024, from
the newest published edition of *Facts & Figures*; quarterly reports from 2025
carry more recent regional conditions. None of it is today's market.

The design response is to date every perishable fact rather than assert it as
current. Price answers say "in 2024" and state that these are annual national
averages, not a farm-gate price and not today's market. Sources carry explicit
never-quote caveats where their figures have expired — the 2005 FAO fertilizer
report's application rates are still sound agronomy, but its prices are in
pre-redenomination cedis and would be wrong by four orders of magnitude if
surfaced.

A farmer is better served by "maize averaged GH₵9,285.91 per tonne in 2024, and
prices vary by region and season" than by a bare number implying currency it
does not have.

## 9. What this does not do

It answers in English, not Twi. The name is Akan, but a clumsy Twi interface judged by a Twi speaker would be worse than none; the localisation here is in the knowledge, not the interface.

Place resolution is partial and says so. The Ghana Meteorological Agency's manual states which regions fall in which agro-ecological zone, so a question naming a region resolves. Towns do not: no source here says Tamale is in the Northern Region, so when Ayekoo makes that step it tells the farmer it is unsourced and that only the region-to-zone link comes from GMet. Regions spanning several zones return every window rather than the largest one.

Prices are 2024 annual national averages, not today's market. Cassava and plantain rest more on West African sources than Ghanaian ones — usable agronomy, but a Ghanaian farmer is getting West African guidance on those two crops, and the answers say so.

Two gaps remain open, and neither is closed by anything above.

**Vegetables have vocabulary but no content.** Okra, pepper, onion and garden egg are named in the alias map, and the corpus holds nothing on growing them. I went looking twice. Every Ghanaian production manual I could find for these crops is a scanned image PDF with no embedded text — one WorldVeg guide yielded 83 characters per page — and the fetcher rejects those rather than admit a document that looks like coverage and holds none. The refusal gate means these questions are declined rather than answered badly, which is the correct failure, but it is still a failure.

**Only numbers and months are verified, not categories.** The checker confirms that a figure or a planting month in an answer occurs in the retrieved passage. It cannot check a claim of kind: the model once described Obatanpa as a hybrid when it is an open-pollinated variety. Extractive quoting avoids this wherever a fact is quoted verbatim, but a generated sentence can still misclassify something the retrieval got right.

## 10. Why this generalises

The corpus is Ghanaian because that is the only honest way to build one. The method is not. Swap the corpus for a Kenyan or Nigerian one and the same pipeline serves those farmers — the contribution is the pipeline and the provenance discipline; the Ghanaian corpus is the proof it works.

The wider result is about model size. A 0.63B model is reliable at *finding* and *summarising* and unreliable at *transcribing precision*. Once that line is drawn — retrieve with the small model, quote where exactness matters, refuse where nothing matches — a model small enough to run on the hardware Africa actually has becomes genuinely useful. The limitation is not knowledge. It is knowing what not to trust it with.
