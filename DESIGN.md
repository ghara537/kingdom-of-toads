# KINGDOM OF TOADS — LIVING DESIGN DOCUMENT

**Version 1.2** — 1 September 2026
**Status: FINAL for prototyping, now being tuned in play.** All design questions are resolved. What remains are balance figures to be tested in play, all of which should be tunable constants rather than hard-coded values. v1.1–v1.2 carry the changes made since the build became playable (see §11).

---

## 1. Overview

Kingdom of Toads is a competitive engine-building board game for 2–6 players. Each player manages a toad kingdom: recruiting toads, bidding on property, assigning toads to work, and feeding them at the end of each round. Most victory points at the end of the final round wins.

**Core tension:** happiness gates how cheaply you can recruit toads, but the only way to raise happiness is to leave toads resting — i.e. not producing. More toads also means more mouths to feed. This squeeze is the heart of the game and should be preserved through all future tuning.

---

## 2. Components

- 1 player mat per player, divided into four work areas: **Fields**, **Mine**, **Military**, **Rest**
- 1 happiness track per player, **1–20**
- Toad tokens (shared general supply)
- Fly tokens (resource)
- Gold tokens (resource)
- Property card deck (auction deck) — **24 types in two decks**, village and city; 67 cards at 4–6 players, 48 cards at 2–3 players, see §6

### Starting setup

**Resolved — every player begins with:**

|               |        |
| ------------- | ------ |
| **Flies**     | **10** |
| **Gold**      | **10** |
| **Toads**     | **2**  |
| **Happiness** | **10** |

Setup is now fully specified.

**Opening round math**, at 10 happiness (the 6–10 band, 3 flies per toad):

- 10 flies buys **3 toads** with 1 fly left over — you cannot afford the full 4-toad cap in round 1, which is a good soft brake.
- That leaves you with 5 toads to place.
- Five toads all in Fields harvests 10 flies; feeding those five costs 5. You end round 1 with roughly 6 flies and 5 toads.
- 10 gold covers three minimum bids of 3, or one serious bid on a card you actually want.

**Starting gold was raised from 5 to 10 in v1.1.** At 5, a player who won the first card of the slate was immediately below the 3-gold eligibility floor and locked out of the rest of the round; simulation showed roughly seven of the twenty-four cards revealed in a 6-round, 4-player game going unsold because nobody left could bid. Ten gold keeps two or three players live through a whole slate, which is what makes the face-up slate a budgeting problem rather than a race to card one.

**Note that 10 sits at the very top of its band.** A single toad in Rest during round 1 pushes you to 11 happiness and drops recruitment from 3 flies to 2 for the rest of the game — a 33% discount for one toad-round. That is a very strong round-1 play and possibly an obvious one. Worth watching whether every player opens the same way; if so, starting at 9 or 11 instead would make the first decision less scripted.

- War tokens — **value varies by round** (see §5, Phase 3), so these need either printed values or a way to record which round each was won in

---

## 3. Resources

**Resolved — the two resources have strictly separate uses. They are not interchangeable.**

| Resource  | Can be spent on                       | Cannot be spent on | Scores?                                                    |
| --------- | ------------------------------------- | ------------------ | ---------------------------------------------------------- |
| **Flies** | Recruiting toads, feeding toads       | Property           | No per-fly VP; 5 VP to whoever holds the most at game end  |
| **Gold**  | Property (auction bids and penalties) | Toads, food        | No per-gold VP; 5 VP to whoever holds the most at game end |

**Resolved — neither resource converts to VP at a per-unit rate.** Gold is purely an auction currency and flies are purely food and recruitment. Hoarding either is only worth doing for the single 5 VP end-game majority.

This is a significant tightening. Unspent gold used to be a safe store of points; now it is dead weight beyond what you need to bid, and beyond whatever margin wins you the majority.

This is the cleanest version of the resource split yet. Flies are the population resource: they buy toads and keep them alive. Gold is the property-and-points resource: it buys cards and, if unspent, converts straight into VP.

The consequence is that **Fields and Mine now serve completely different strategic goals**. Fields grows and sustains your kingdom; Mine buys engine upgrades and banks points. Neither can bail out a shortfall in the other, so the placement decision each round is genuinely hard.

---

## 4. The Happiness Track

Range **1–20**. Happiness determines the cost to recruit each toad. It is pushed **up** by Rest toads and certain cards, and **down** by losing the war each round (§5, Phase 3). **It no longer scores per point** — its only direct VP contribution is the 5 VP end-game majority (§7). Everything else it does is instrumental: cheaper toads.

**Resolved — recruitment cost bands:**

| Happiness | Cost per toad |
| --------- | ------------- |
| 16–20     | 1 resource    |
| 11–15     | 2 resources   |
| 6–10      | 3 resources   |
| 1–5       | 4 resources   |

Bands are skewed to the high side deliberately: cheap recruitment should feel earned.

**Resolved — the track floors at 1. Zero is not a reachable state.** Happiness caps at 20 and bottoms out at 1; any loss that would take a player below 1 simply stops there, and the excess is forfeited. The same applies at the top.

This is a deliberate anti-death-spiral rule. Every player can always recruit toads on every turn, no matter how badly the previous round went — the worst position on the board is expensive, not paralysing. A player who overextends and starves is punished by paying 4 resources a toad while their rivals pay 1, which is a steep enough hill to climb without also locking them out of the game entirely.

---

## 5. Round Structure

The game runs a fixed number of rounds (see §8). Each round has four phases, resolved in order by all players.

### Phase 1 — Toad Recruitment

**Resolved — recruitment is simultaneous and secret. There is no player order anywhere in this game.**

- All players **secretly declare how many toads they are recruiting** and how many flies they are committing, then **reveal together**.
- Each player may recruit **up to 4 toads** this phase.
- **Cost is paid in flies only.** Gold cannot be used to recruit.
- Each toad costs the number of **flies** shown by your current happiness band (§4).
- Newly recruited toads are available to work in Phase 3 of the same round, and must be fed in Phase 4 of the same round.

**Resolved — the toad supply is not capped.** There is no limit on the total number of toads in play. A player is constrained only by flies, happiness and the 4-toad recruitment cap.

The rotating player order from v0.5 is **removed**. With an uncapped supply nothing was ever contested during recruitment, so the order changed no outcome — it was pure table ceremony. Simultaneous reveal is faster and adds a small read: seeing three rivals each field four fresh toads tells you something about the placement phase to come.

Recruitment, placement and feeding are now all simultaneous. The **auction is the only phase with any sequencing at all**, and even that is sequencing of cards rather than of players.

### Phase 2 — Property Auction

**Resolved — the full round's slate is revealed face-up at once, then auctioned one card at a time in the order revealed.**

- Reveal property cards **equal to the number of players**, all face-up, **drawn from the deck the round calls for** — village early, city late (§6a).
- **Resolved (v1.1) — the slate is revealed a full round in advance.** As soon as a round's auction finishes, the *next* round's slate is dealt face-up. Round 1 is the exception: its slate is revealed at the start of its own auction, because there is no earlier round to reveal it in.
- Cards are then auctioned **in the order they were revealed**, one at a time.
- **Bids are paid in gold only.** Flies cannot be bid.
- **Minimum bid: 3 gold.**
- **Resolved — a player holding fewer than 3 gold cannot bid at all.** They are out of the auction entirely until they mine more. This is not just a floor on bid size; it is an eligibility requirement.
- **Resolved — there is no cap on how many properties a player may take.** A gold-rich player can sweep the entire slate in a round if they can afford it, and that is a legitimate reward for investing in Mine.
- **Resolved — you may never bid more gold than you currently hold.** No credit, no borrowing, no bidding against a later harvest. This is a hard cap, and it is final.

**Why reveal a round early.** Gold is mined in Phase 3 and spent in Phase 2 of the _following_ round, so under the old timing you had to decide how many toads to put in the Mine before knowing what your money would be for. Mining was a blind bet on the deck. Dealing the slate at the end of the previous auction closes that gap: you place your toads already knowing what is coming up for sale and roughly what it will cost you, which turns Mine placement into a real decision instead of a hedge.

It also stretches the budgeting problem across two rounds rather than one. You are no longer only choosing between the cards on the table; you are choosing whether to spend now or hold for what you can already see coming.

The cost is information. Nothing about the auction is concealed any more except what people intend to bid, and the shuffle stops being a source of surprise a round earlier than it used to be.

**Why a cap rather than an overbid penalty.** An alternative was considered in v0.20: remove the ceiling and punish players who bid more than they can pay. It was rejected for three reasons.

1. **Any gold penalty is uncollectable from the player most likely to trigger it.** A player holding 1 gold cannot be fined 3. The penalty is denominated in exactly the resource the offender has run out of.
2. **In blind mode, overbidding has no upside anyway.** A sealed first-price bid means the winner pays their own bid, not the runner-up's — so a broke player bidding wildly costs the eventual winner nothing. It is pure noise with a cleanup rule attached.
3. **In live mode, overbidding is free griefing.** Open ascending bidding is precisely where dragging a rival up hurts them, and a player with no gold has no exposure. Every auction would become the poorest player chasing every card to the ceiling.

The mechanic is therefore useless in one auction mode and broken in the other. Making it work would require a penalty in a currency nobody can be broke in — culling a toad, or negative VP at scoring — which means building a scoring subsystem to protect a mechanic whose only benefit was that bluffing feels good.

The cap does mean **a player's bluffing power shrinks as they get poorer**. That is intended. A poor player should be weak at the auction; that is what losing the gold race means.

**Why the whole slate is face-up.** This is the most consequential change in this version. Because you can see every card before bidding on the first one, and because gold spent on card 1 is gone by the time card 3 comes up, the auction becomes a **budgeting problem across the whole round rather than a series of isolated bids**. If the Grand Monument is fourth in the queue, you have to decide whether to let the first three go. If you are short on gold you may have to pick your one fight and pass on everything else — while a rival with a deep purse can bid you up on a card they do not even want, knowing you cannot afford both.

Reveal order therefore matters a great deal, and should be genuinely random rather than sorted.

### Auction mode — a game setting

**Resolved — the auction format is a toggle in game settings**, so both can be tested against each other:

**`AUCTION_MODE = blind`** _(default)_

- All players secretly commit a bid for the current card, then reveal together.
- Highest bid takes the card and pays; everyone else pays nothing.
- Keeps the bluffing and player-reading tension, and plays fast because nobody waits through a back-and-forth.

**`AUCTION_MODE = live`**

- Open ascending auction. Players call rising bids until all but one have passed.
- The last remaining bidder takes the card and pays their final bid.
- Slower and louder, and it leaks more information — a player's reserves become visible through what they are willing to chase.

The tie rules below apply to **blind mode only**. A live ascending auction cannot produce a tie, since bidding continues until everyone but one player has passed.

**Resolved — tie resolution (blind mode):**

1. If two or more players tie for the highest bid, those players go to **exactly one blind re-bid**.
2. Each tied player secretly commits a new bid that must be **equal to or higher than** the tied amount, and never higher than the gold they hold. Bids are revealed together.
3. If one player has bid higher than the others, they take the card and pay their new bid.
4. **If the re-bid is tied again**, the tied players have failed to negotiate: each pays a **3 gold penalty**, nobody receives the card, and the **card is discarded from the game entirely**.

One re-bid, then it's over. Two tied rounds in total.

**Equal-or-higher is the key clause, and it changes who holds the power.** Because a player may simply repeat the tied amount, nobody is ever forced out of a tie-off by not being able to raise. That eliminates the attrition problem the previous version had, where the deepest purse won automatically by outlasting a poorer rival who had committed their whole holding.

Now the burden sits on the richer player. If the poorer player re-bids the same amount again, the richer player has two options: **go higher and actually pay more for the card, or match and lose it entirely** along with 3 gold. Winning a contested card requires paying for it, not merely having more money than the other person.

**The re-bid is a game of chicken.** Matching the tied amount is a credible threat — "I'll burn this card rather than let you have it cheap" — and it costs the threatener only 3 gold, while denying a card the rival clearly wanted. A player who is out of the running for a card can still use the tie-off to make their rival overpay.

**Why the 3 gold eligibility floor matters here.** Because nobody can bid without holding at least 3 gold, **every player who reaches a tie-off can always pay the 3 gold penalty**. There is no state in which a player triggers the penalty and cannot cover it. That is why the floor is an eligibility requirement rather than merely a minimum bid size.

### Phase 3 — Worker Placement

Players simultaneously and **secretly** assign their toads across the four areas of their mat, then reveal together.

| Area | Effect |
| ---- | ------ |

**Resolved — production rates (fixed all game):**

| Area         | Per toad                                          |
| ------------ | ------------------------------------------------- |
| **Fields**   | **+2 flies**                                      |
| **Mine**     | **+2 gold**                                       |
| **Rest**     | **+1 happiness**                                  |
| **Military** | Contributes strength to the war, produces nothing |

**Resolved — majority bonuses escalate by +1 each round. There is no halfway doubling.**

- The bonus starts at **+2 in round 1 and increases by 1 each round**. Formula: `bonus = round number + 1`.
- The **war token's VP value** escalates on the same curve, starting at **2 VP in round 1**. Formula: `war token VP = round number + 1`.
- **The Rest bonus escalates on a slower curve — it increases by 1 every other round**, starting at +1. Formula: `Rest bonus = round number rounded up, divided by 2` (`ceil(round / 2)`).
- A halfway doubling was considered in v0.12 and **removed in v0.13**. Stacked on top of the existing escalation it produced a 2.5× cliff at round 4 and pushed roughly four fifths of all bonus value into the back half of the game, making rounds 1–3 close to a rehearsal. The single steady curve does the same job with a much cleaner shape.

| Round | Fields bonus | Mine bonus | Rest bonus       | War token |
| ----- | ------------ | ---------- | ---------------- | --------- |
| 1     | +2 flies     | +2 gold    | +1 happiness     | 2 VP      |
| 2     | +3 flies     | +3 gold    | +1 happiness     | 3 VP      |
| 3     | +4 flies     | +4 gold    | **+2 happiness** | 4 VP      |
| 4     | +5 flies     | +5 gold    | +2 happiness     | 5 VP      |
| 5     | +6 flies     | +6 gold    | **+3 happiness** | 6 VP      |
| 6     | +7 flies     | +7 gold    | +3 happiness     | 7 VP      |

Both curves extend naturally if you test at 7–10 rounds: the formulas are game-length independent.

**On the Rest curve.** Over a full 6-round game a player who won every Rest majority collects 12 happiness from bonuses alone, against 27 flies or 27 gold for the equivalent Fields or Mine run. That gap is appropriate — happiness scores nothing per point, so its value is entirely in cheaper recruitment and the one 5 VP majority. The slower curve keeps Rest worth contesting into the back half without letting a Rest-focused player run to the 20 cap and sit there.

- **Majority bonuses** go to the player with the most toads placed in Fields, Mine or Rest. The bonus is a flat amount for the turn, not per toad.
- **War:** the player with the most toads in Military wins the war and takes a war token worth that round's value. Military toads produce no resources.

**Resolved — losing the war costs happiness, and this applies to every non-winner.** Every player other than the war's winner **loses 1 happiness** that round, floored at 1 as always. It makes no difference whether you fielded Military toads and were beaten or ignored Military entirely — if you did not win, you lose the point.

This is the first systematic downward pressure on the happiness track — until now only starvation pushed it down, and that was optional. It changes the character of Military considerably:

- **War is now effectively compulsory.** Sitting out is no longer free; it costs you a point of happiness every round, and six rounds of that takes a starting player from 10 down to 4, dropping them two full recruitment bands. Ignoring Military is a slow bleed rather than a neutral choice.
- **It gives the happiness economy a floor to fight against.** Rest toads now have to work to hold ground, not just climb, which makes the +1-per-toad rate feel less anaemic than it did.

There is no opt-out. A player who never places a toad in Military still bleeds a point every round, which over six rounds is the difference between the 6–10 and 1–5 recruitment bands. Military is not a strategy you can decline — it is a tax you either pay in toads or pay in happiness.

**Resolved — the penalty only applies if the war was actually won.** If the war is tied, no token is awarded and **no player loses happiness**, including everyone who stayed out of Military entirely. The penalty is tied to there being a victor, not to the war having taken place.

This makes a tied war a genuinely neutral round rather than a table-wide punishment, and it gives the war a second, subtler layer: a player who cannot win the war outright can still **deny** it. Matching the leader's Military count exactly costs them the token _and_ spares the entire table the happiness loss. That's a real spoiler play, and it's cheap — you only need to match, not beat.

Expect this to shape the Military bidding war considerably. The leader now has to overcommit to avoid being pegged, which pulls toads away from Fields and Mine.

> **Needs a ruling:** does the **Rest bonus escalate too?** It's shown flat at +1 above because you only specified escalation for flies and gold. Leaving it flat means happiness quietly becomes the least contested area as the game goes on. Escalating it on the same curve would make a late Rest majority a fast route up the recruitment bands — though happiness caps at 20, which limits the runaway.

**Resolved — ties award nothing, in every category including war.** If two or more players tie for the most toads in a category, **no bonus is handed out for that category at all** — it is not split, and it does not carry over. A tie in Military means **no war token is awarded that round**.

The **regular production is still paid in full**: everyone still collects their 2 flies, 2 gold or 1 happiness per toad placed, tied or not. Only the bonus layer evaporates. This keeps ties clean to resolve and makes going for a majority a real gamble — matching your rival exactly is the worst outcome for both of you.

Note that Military is the harsh one: it has no regular production underneath the bonus, so a tie in war means those toads produced literally nothing that round _and_ still have to be fed. That's intentional for now — war is the high-risk play.

### Phase 4 — Feeding

- **Resolved — every toad must be fed 1 fly.** No exceptions, no discount for toads that were resting or at war.

This rate is what makes Fields worth placing in. A toad in Fields produces 2 flies and eats 1, so it nets +1 fly per round and pays for one other toad besides itself. Any lower a production rate, or any higher a feeding cost, and a Fields toad would only feed itself and the economy would not grow without majorities or cards.

- Any toad you cannot feed **starves** and is returned to the supply.
- **Resolved — each starved toad costs you 1 happiness**, floored at 1 as always. Losing three toads in a round is a 3-point drop, enough to move you a full recruitment band.
- **Resolved:** feeding **still applies in the final round**, before scoring. Without it the last round becomes a consequence-free free-for-all where you overextend for points — feeding keeps the pressure on right to the end.

**Resolved — starvation is a player choice.** You decide how many toads you want to keep alive and feed exactly that many; the rest starve and return to the supply. Nothing is forced or random.

In practice this makes feeding a deliberate downsizing decision rather than a punishment inflicted on you — but the happiness cost means it is never free. Deliberately starving toads to win the end-game fly majority costs 1 VP per toad _and_ a happiness point each.

**This got cheaper in v1.1**, when a toad dropped from 2 VP to 1. Starving three toads in the final round to take the 5 VP fly majority is now a clear profit rather than a marginal one, and the happiness point no longer bites in a round where happiness has stopped mattering. If the last round turns into a routine cull, the fix is to raise the starvation penalty rather than to put the toad's VP back.

Between starvation and the war penalty, happiness has two independent sources of downward pressure. A player who loses the war and starves two toads drops 3 points in a single round.

---

## 6. Property Cards

### Development: village and city

**Resolved (v1.2) — the deck is split into two, and the game deals from one then the other.** Every card is either a **village** card or a **city** card. The first half of the game auctions only village cards; the second half auctions only city cards.

- The turn happens at **round 4 of 6**. In general the city deck takes over at `floor(rounds / 2) + 1`, so an 8-round game turns at round 5 and a 10-round game at round 6. **Round 1 is always village.**
- The round-ahead reveal (§5, Phase 2) crosses the boundary: the last village round's placement reveals the first city slate, so you see the city era coming while you still have a village round in which to prepare for it.

**Why split the deck.** Under a single shuffle the Grand Monument was as likely to appear in round 1 as round 6, which made the arc of a game a matter of shuffle luck rather than design. Splitting gives the game a shape: village cards are small, cheap and cheaply gated — one or two toads — so the early rounds are about building something; city cards are larger, want three toads in an area, and carry most of the end-game scoring, so the late rounds are about converting what you built.

It also gives the auction a rhythm. Village gold is spent on engines that will pay out over five more rounds; city gold is spent on points, or on an engine with two rounds left to run. The same purse means different things at different times.

| | Types | Cards at 4–6p | Cards at 2–3p |
| --- | --- | --- | --- |
| **Village** | 12 | 35 | 24 |
| **City** | 12 | 32 | 24 |
| **Total** | **24** | **67** | **48** |

**Supply check.** A 6-player game reveals 18 village and 18 city cards, out of 35 and 32. A 3-player game reveals 9 of each half of a 24-card pool. Every count leaves headroom for cards removed permanently by a tie-off, and no half can run dry at 6 rounds. At 10 rounds and 6 players the village half is drawn to 30 of 35, which is tight but holds.

### Card groups

**Resolved — 24 card types.** Engine, instant and flat-scoring cards have **3 copies each**; conditional scoring cards have **2 copies each**. See the scaling table below for 2–3 player games.

### Engine cards — ongoing effect, **2 VP each**

Threshold-gated: the effect only triggers if you have at least the stated number of toads in that area at the time of the harvest.

| Card                | Dev     | Requirement           | Effect                  | VP  | Copies |
| ------------------- | ------- | --------------------- | ----------------------- | --- | ------ |
| Fly Farm            | village | ≥2 toads in Fields    | +2 flies each round     | 2   | 3      |
| Gold Seam           | village | ≥2 toads in Mine      | **+3 gold** each round  | 2   | 3      |
| Lily Gardens        | village | **≥1 toad in Rest**   | +2 happiness each round | 2   | 3      |
| Barracks            | village | —                     | +1 military strength    | 2   | 3      |
| **Militia Post**    | village | **≥1 toad in Military** | **+2 gold** each round | 2   | 3      |
| **Tadpole Nursery** | village | **≥2 toads in Rest**  | **+1 toad** each round  | 2   | 3      |
| Great Marsh         | city    | ≥3 toads in Fields    | +4 flies each round     | 2   | 3      |
| Deep Vein           | city    | ≥3 toads in Mine      | **+5 gold** each round  | 2   | 3      |
| War College         | city    | —                     | +2 military strength    | 2   | 3      |
| **Mercenary Camp**  | city    | **≥2 toads in Military** | **+4 gold** each round | 2 | 3      |

**Subtotal: 10 types, 30 cards.**

**Militia Post and Mercenary Camp are the first production Military has ever had.** Until v1.2 a Military toad produced literally nothing — the war was, as §5 puts it, a tax you either pay in toads or pay in happiness. These two pay a **flat amount per round, not per toad**, so they reward *entering* the war rather than winning it by weight of numbers: one toad turns the tap on, and a second only matters if you also hold the Camp.

Watch whether this makes Mine redundant for anyone holding both. Two toads in Military with both cards yields 6 gold a round — better than the same two toads in the Mine — and those toads are contesting the war at the same time.

**Tadpole Nursery is the first card that breeds.** The toad arrives after placement, so it works from the following round, but it must be fed at the end of this one. It gives Rest a second reason to exist beyond happiness, which matters because Rest is the most frequently tied area in simulation.

### Activated cards — the owner chooses

**Resolved (v1.2) — one card group carries a decision.** Every other card in the deck is automatic. An activated card is permanent and scores like the rest, but its ability is an option its owner may take or decline each time it comes up.

| Card          | Dev     | Ability                                                | VP  | Copies |
| ------------- | ------- | ------------------------------------------------------ | --- | ------ |
| **Austerity** | village | In any feeding phase: **skip feeding entirely** for **5 happiness** | 2 | 3 |

Austerity feeds the whole kingdom or none of it — you cannot skip feeding *and* starve toads for the fly majority in the same round. It is usable every round, but the happiness track limits it: from 10 happiness you get two uses before hitting the floor, and the floor is the 4-flies-a-toad recruitment band.

**This is a deliberate exception to a rule §6 states plainly below** — that there is no decision to make about a card once you own it. It earns the exception because it is the only lever a player has against a starvation spiral, and the spiral is otherwise unrecoverable: you starve, you lose happiness, toads get dearer, you starve again. One card that costs a lot of happiness to stop the bleeding is a fair escape hatch. If more activated cards follow, that rule should be rewritten rather than repeatedly excepted.

**Gold engine cards are deliberately rated one step above their fly counterparts** (+3/+5 against +2/+4). Gold has no direct VP value, so a gold engine has to earn its keep entirely by converting into auction wins — which means it needs to out-produce a fly engine to be worth the same bid. The extra point per round is that premium.

All engine cards are flat 2 VP regardless of how strong the effect is. Balance is handled entirely by the auction — a Great Marsh should simply cost more gold than a Fly Farm, and it's the players who decide by how much. That's a good use of a silent-bid auction and means you don't have to get the VP curve right on paper.

### Instant cards — resolve immediately on purchase, **2 VP each**

Two per effect category, a larger and a smaller.

| Card          | Dev     | Category  | Effect                   | VP  | Copies |
| ------------- | ------- | --------- | ------------------------ | --- | ------ |
| Public Park   | village | Happiness | +3 happiness immediately | 2   | 3      |
| Larder        | village | Flies     | **+4 flies** immediately | 2   | 3      |
| Tadpole Pond  | village | Toads     | Gain **1 toad** free     | 2   | 3      |
| Festival      | city    | Happiness | +5 happiness immediately | 2   | 3      |
| Granary       | city    | Flies     | **+8 flies** immediately | 2   | 3      |
| Spawning Pool | city    | Toads     | Gain **3 toads** free    | 2   | 3      |

**The village instants were cut in v1.2** — Larder from 5 flies to 4, Tadpole Pond from 2 toads to 1 — so that the pairs read as village-then-city rather than as two sizes of the same thing. A city instant should feel like a different order of magnitude, not an increment.

**Subtotal: 6 types, 18 cards.**

**Resolved — all instants are a flat 2 VP**, regardless of effect size. As with the engine cards, the auction prices them.

**Resolved — toads from Spawning Pool and Tadpole Pond arrive immediately and can be placed in Phase 3 of the same round.** They must also be fed in Phase 4 of that round.

This makes the toad instants the strongest cards in the deck by a distance. Spawning Pool gives 3 toads in a round where the recruitment phase has already closed — bypassing the 4-toad recruitment cap, the happiness band, and the fly cost all at once. At 10 happiness that's 9 flies of value, plus 3 VP of toads, plus three extra bodies working the same turn you buy it.

**On Granary at +8:** this is the largest single resource grant in the deck. At 10 happiness that's nearly three toads' worth of recruitment, or eight rounds of feeding for one toad. It doesn't bypass the 4-toad cap the way Spawning Pool does, and the flies arrive too late in the round to be spent on recruitment until the _following_ round — so it's a slower payoff than the toad instants, but a larger one in raw value. It also makes Granary a live play for the end-game **most flies** 5 VP majority: bought in round 6, it is 8 flies dropped onto the table after everyone else has finished spending.

Two consequences worth tracking in playtesting:

- **A player can exceed 4 new toads per round** by winning a toad instant, which is the only way to break that cap. That's a legitimate strategy, not a loophole, but it means the cap is softer than it reads.
- **Buying one late is close to pure VP.** A Spawning Pool bought in round 6 is 2 VP for the card plus 3 VP of toads for 3 flies of feeding — 5 VP for a modest gold bid. That may make it the most contested card in the endgame, which is fine, but watch that it doesn't dominate the final auction every single game. The v1.1 drop to 1 VP a toad halved this play's payoff and makes the late Spawning Pool a good card rather than an automatic one.

### Flat scoring cards — **3 copies each**

| Card           | VP  | Copies |
| -------------- | --- | ------ |
| Monument       | 5   | 3      |
| Grand Monument | 10  | 3      |

**Subtotal: 2 types, 6 cards.**

### Conditional scoring cards — **2 copies each**

| Card                  | Dev     | Scores                            | Copies |
| --------------------- | ------- | --------------------------------- | ------ |
| **Almshouse**         | village | **1 VP per 3 happiness** at game end | 2   |
| Census                | city    | 1 VP per 2 toads at game end      | 2      |
| Treasury              | city    | 1 VP per 3 gold at game end       | 2      |
| Hall of Victories     | city    | 2 VP per war token you hold       | 2      |
| **Guildhall**         | city    | **1 VP per 2 property cards** you own | 2  |

**Almshouse gives happiness a second way to score.** Until v1.2 happiness paid out only through cheaper recruitment and the single 5 VP majority, which made it the most instrumental thing on the board. A card that converts a high track into points — and only for the player who won the auction for it — is a lighter touch than restoring a per-point rate.

**Guildhall rewards the player who swept the auction**, which is the strategy simulation says currently loses. It is the only card that scores off other cards, so it also quietly rewards buying cheap village cards early.

**Subtotal: 3 types, 6 cards.**

These are the scarcest cards in the deck and the most strategically loaded. **Treasury** is the direct answer to gold feeling weak: it quietly restores gold-as-points, but only for a player who won an auction to get it. Hoarding gold is no longer automatically safe — it's a bet that pays off only if you land the right card.

### Deck totals

| Group               | Types  | Cards  |
| ------------------- | ------ | ------ |
| Engine              | 10     | 30     |
| Activated           | 1      | 3      |
| Instant             | 6      | 18     |
| Flat scoring        | 2      | 6      |
| Conditional scoring | 5      | 10     |
| **Total**           | **24** | **67** |

### Deck scaling by player count

**Resolved — at 2 and 3 players, every card is at 2 copies, flat.** Engine, instant and flat-scoring cards drop from 3 copies to 2; conditional scoring cards stay at 2. The low-count deck is simply the full set of 24 types, doubled.

| Group               | Types  | 4–6 players | 2–3 players |
| ------------------- | ------ | ----------- | ----------- |
| Engine              | 10     | 30          | 20          |
| Activated           | 1      | 3           | 2           |
| Instant             | 6      | 18          | 12          |
| Flat scoring        | 2      | 6           | 4           |
| Conditional scoring | 5      | 10          | 10          |
| **Total**           | **24** | **67**      | **48**      |

The flat rule is easier to remember and to sort physically than "remove one of each" — two of everything, no exceptions.

**Supply check.** See the per-deck table at the top of §6: each half is drawn separately, so the figure that matters is 18 of 35 village and 18 of 32 city at 6 players, not the combined total.

**Conditional scorers become proportionally more common at low counts** — 6 of 36 rather than 6 of 51 — which is the right way round. With fewer cards surfacing overall, keeping the strategically loaded cards at full strength means Treasury and Census are likely to appear rather than being a coin flip. A gold-heavy player at 3 players can reasonably expect their payoff to exist.

### Card permanence and timing

**Resolved — every card you buy is yours for the rest of the game and counts toward victory points at scoring. Nothing is ever discarded, spent or returned.** What differs between card groups is only _when_ the effect fires:

| Group                   | When the effect fires                              | Kept for VP?     |
| ----------------------- | -------------------------------------------------- | ---------------- |
| **Engine**              | Every round, automatically, during Phase 3         | Yes — 2 VP       |
| **Activated**           | Any round the owner chooses, at its stated cost     | Yes — 2 VP       |
| **Instant**             | Once only, at the moment of purchase               | Yes — 2 VP       |
| **Flat scoring**        | Never — the card has no effect                     | Yes — 5 or 10 VP |
| **Conditional scoring** | Never during play; evaluated once at final scoring | Yes — as printed |

So an instant card is a one-off burst of material followed by a permanent 2 VP, and a flat scoring card does nothing at all except sit in front of you and be worth points. There is no upkeep and, for every group but one, no decision to make about a card once you own it — buying it is the only choice.

**The exception is the activated group** (Austerity, above), added in v1.2. It is the only card whose owner chooses whether to use it, and it costs happiness rather than an upkeep in resources. The rule above still describes 23 of the 24 types.

**Resolved** — there is no cap on how many cards one player may hold, consistent with the auction rule that a player may take as many properties per round as they can afford.

## 6a. Information Visibility

**Resolved — all materials are public knowledge.** Every player's **toads, flies and gold** are open information at all times, as are their happiness track position and the property cards they own. Nothing about a player's holdings is concealed.

**The auction slate is public a round ahead** (§5, Phase 2). Both the round in progress and the round to come are face-up on the table, and every player sees them at the same moment.

**What is hidden is intention, not position.** Three phases involve secret commitment followed by simultaneous reveal:

- **Phase 1 recruitment** — how many toads you are buying
- **Phase 2 blind auction** — what you are bidding for the current card
- **Phase 3 placement** — where your toads are going

So you always know what a rival _can_ do and never what they _will_ do. That is the right split for this game: the tension comes from reading intent, not from tracking hidden inventories.

Two consequences follow directly:

**The bid ceiling enforces itself.** Because gold is face-up, nobody can bid more than they hold without the table noticing immediately. The rule needs no honour system and no reveal-on-challenge (§5, Phase 2).

**Bluffing at auction is bounded, deliberately.** Rivals can count your coins and know your maximum bid before you make it. You can still surprise them with _how much_ of your purse you commit, but never with more than you have. This is the same reasoning that settled the overbid question in v0.21 — a poor player should be visibly poor at the auction.

---

## 7. Scoring

Scored at the end of the final round, after that round's feeding phase.

| Source                  | Value                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| Each surviving toad     | **1 VP**                                                                  |
| Each war token          | **2–7 VP**, per the round it was won in                                   |
| Property cards          | **As printed** — 2 VP engine and instant, 5 or 10 VP flat, or conditional |
| Each gold               | 0 VP                                                                      |
| Each point of happiness | 0 VP                                                                      |
| Each fly                | 0 VP                                                                      |

**Resolved — only toads, war tokens and property cards score per unit.** Gold and happiness both had their per-unit VP removed. Everything else that matters is now a one-off majority award.

**Resolved (v1.1) — a toad is worth 1 VP, down from 2.** At 2 VP a toad, simulation put roughly 43% of all victory points on the board into toad count alone, and a strategy that simply grew its population and ignored the auction won about two thirds of games. Toads were both the engine and the score, which left property cards — 2 VP for an effect you have to bid gold for — looking like a poor substitute for just recruiting another toad.

At 1 VP the toad is still the thing you build, but it pays off through what it produces rather than by sitting on your mat. Property drops from a sideshow to about a third of the points scored, and the auction has to be contested rather than conceded.

Watch two things in play. Toad count is still the **first tie-breaker** (§8), so it retains value beyond its 1 VP. And feeding is now cheaper to walk away from — see the note in §5, Phase 4.

**Simulation note (v1.2): dropping the toad to 0 VP was tested and not adopted.** Across 250 bot games at 4 players:

| VP per toad | Population strategy wins | Winner-to-last spread | Toads starved per game |
| ----------- | ------------------------ | --------------------- | ---------------------- |
| 2           | 97%                      | 67 VP                 | 14.0                   |
| 1           | 87%                      | 47 VP                 | 14.0                   |
| 0           | 60%                      | 30 VP                 | 17.5                   |

Zero makes the game markedly closer — the spread between first and last halves — but it does not dethrone the population strategy, which still wins three games in five. **That is the important finding: toad VP was amplifying an advantage that does not come from toad VP.** With the toad worth nothing, a large population still wins most flies, most happiness and most wars; the majorities alone were worth more to that player than the toads had been.

The cost of zero is that a toad becomes free to discard. Starvation rose by a quarter, because in the final round a toad costs nothing to kill and the flies it would have eaten count toward a 5 VP majority. The last round turns into a cull.

So the lever for closing the gap is not the toad's VP. It is the end-game majorities, which is where that player's points actually come from.

### End-game majority bonuses

**Resolved — three one-off awards of 5 VP each, checked once at final scoring:**

| Award              | Value |
| ------------------ | ----- |
| **Most happiness** | 5 VP  |
| **Most gold**      | 5 VP  |
| **Most flies**     | 5 VP  |

- These are the **only** way gold, happiness and flies contribute to your final score.
- **Ties award nothing**, consistent with the majority rule in Phase 3. If two players tie for most flies, neither takes the 5 VP.
- These are checked **after the final round's feeding phase**, at the same moment as everything else. Toads starved in round 6 are already gone when "most flies" is counted.

Notes on what this does to the endgame:

**All three resources now behave identically at scoring time** — worthless in bulk, worth exactly 5 VP if you top the table. That's clean and easy to teach, and it means a player can pick one track to win rather than spreading thin across all three.

**The final feeding phase stays tense.** Starving a toad saves 1 fly but costs 1 VP, so it is worth doing whenever a couple of flies would swing the 5 VP fly majority. Since v1.1 this is a live calculation rather than a rare one — see §5, Phase 4.

**Happiness is now purely instrumental plus a prize.** It gates recruitment all game and awards 5 VP at the end. That's a much lighter load than v0.6 put on it.

All VP values should be treated as **tunable constants in the code, not hard-coded numbers** — these will almost certainly move during playtesting.

---

## 8. Game End and Tie-breakers

- **Game length:** 6 rounds to start. Expect to test anywhere in the 6–10 range.
- The game ends after the final round's feeding phase; scoring follows immediately.

**Resolved — tie-breakers, in order:**

1. Most victory points
2. **Most toads**
3. **Highest happiness**

Toads first, happiness second. This is the reverse of v0.6 and it's the right way round now: whoever has the most happiness has usually already collected the 5 VP majority for it, so using happiness as the _first_ tie-breaker would have re-awarded the same player twice. Toad count is independent of any bonus and does real work.

---

## 9. Player Count Notes

**Resolved — 2 players works as-is.** War becomes a much lower-stakes side contest between two people rather than a table-wide scramble, but it's still worth points and still something to genuinely fight over. No special 2-player rules for now; revisit only if playtesting shows the majority bonuses are trivially won.

At 6 players, six cards hit the auction each round, so a lot of property enters play — worth watching whether the deck runs dry before round 6.

---

## 10. Open / To Design

Nothing structural remains. The rules are complete enough to build and play. What is left is small:

**Nothing structural is open.** The design is complete; what follows are balance questions being answered in play.

The only item carried forward is a timing detail that follows naturally from the rules as written: the three end-game majorities are checked **after** the final round's feeding, so toads starved in round 6 are already gone when "most flies" is counted.

What remains are playtest questions rather than design decisions:

- Are the gold engine rates (+3/+5) the right premium over their fly equivalents?
- Does the war denial play — tying the war to spare the table its happiness loss — prove too strong?
- Does the tie-off chicken game cause too many cards to leave the deck at 5–6 players?
- Does everyone open round 1 with a Rest toad to cross from happiness 10 into the 11–15 band?

Opened by the v1.2 changes:

- **Do Militia Post and Mercenary Camp make the Mine redundant?** Two toads in Military holding both cards out-earn two toads in the Mine, and fight the war as well.
- **Is the village half too thin at 6 players?** 18 of 35 revealed is comfortable at 6 rounds; at 10 rounds it becomes 30 of 35.
- **Does Austerity blunt the feeding squeeze §1 calls the heart of the game?** It is meant as an escape from a starvation spiral, not a licence to ignore the brake.
- **Does the round-4 boundary feel like a gear change or an interruption?** The whole point is that it should give the game an arc.

Opened by the v1.1 changes:

- **Is 1 VP a toad now too little?** Toads are still the engine, and toad count is still the first tie-breaker, but they no longer pay for themselves at scoring. Watch whether players stop recruiting in the back half.
- **Does the final round become a routine cull?** Starving a toad now costs 1 VP and a happiness point that no longer matters, against a 5 VP fly majority. If so, raise the starvation penalty rather than restoring the toad's VP.
- **Does the round-ahead slate make Mine placement too easy?** It was meant to turn a blind bet into a decision. It may instead have turned it into arithmetic.
- **Is the auction now the whole game?** Property rose from roughly a quarter of all points scored to a third when the toad dropped to 1 VP. That was the intent, but a third is close to the point where a player who loses the gold race cannot recover.

Closed since v0.1: auction format, auction tie resolution, final-round feeding, game-end tie-breaker, flies scoring, happiness band boundaries, 2-player viability, happiness floor, tie handling in all categories, production rates, majority bonus sizes, bonus escalation, war token values, resource use restrictions, turn order, starvation choice, gold and happiness per-unit VP removed, tie-breaker order, starting resources, full card list and deck composition, instant card values, timing of free toads, complete starting setup, war loss penalty, bonus curve shape, Rest bonus escalation, gold engine card rates, scope of the war happiness penalty, war tie handling, deck scaling, gold majority retained, uncapped toad supply, starvation penalty, low-count deck composition, recruitment simultaneity, auction slate reveal, auction mode toggle, bid ceiling, properties per player, fly instant naming, bid ceiling versus overbid penalty, auction eligibility floor, tie-off length, tie-off bidding rule, feeding cost, card holding limit, card permanence and effect timing, full information visibility.

---

## 11. Change Log

**v1.2 — 1 Sep 2026** — **The deck is split into village and city halves**, dealt in the first and second halves of the game respectively (`floor(rounds / 2) + 1` is the first city round). **Six new cards**: Militia Post and Mercenary Camp, the first production Military has ever had, paid flat per round rather than per toad; Tadpole Nursery, the first card that breeds toads; Almshouse, giving happiness a second way to score; Guildhall, which scores off property held; and **Austerity, the first card with a decision attached** — skip feeding entirely for 5 happiness, in any round. Village instants trimmed so the two halves read as different orders of magnitude: Larder 5 → 4 flies, Tadpole Pond 2 → 1 toad. Lily Gardens now needs only 1 toad in Rest. Deck grows from 18 types to 24.

**v1.1 — 28 Aug 2026** — First tuning pass from the playable build. **Starting gold raised from 5 to 10**, so winning an early card no longer prices you out of the rest of the slate. **The auction slate is now revealed a round in advance** — dealt face-up as soon as the previous round's auction ends — so toads are placed already knowing what is coming up for sale; round 1 still reveals at the start of its own auction. **A surviving toad is worth 1 VP, down from 2**, moving points out of raw population and into property, the war and the majorities.

**v0.17 — 27 Aug 2026** — Deck scales down by one copy of every card at 3 players and below (33 cards). The "most gold" 5 VP end-game majority confirmed to stay. Toad supply uncapped. Each starved toad costs 1 happiness. Gold engine rates held at +3/+5. **Design considered feature-complete.**

**v1.0 — 27 Aug 2026** — All property cards confirmed permanent and kept for victory points regardless of type; only the timing of their effects differs. All materials — toads, flies, gold, happiness and owned cards — are public knowledge, with only recruitment, bidding and placement decisions hidden until simultaneous reveal. **No open design questions remain.**

**v0.24 — 27 Aug 2026** — Feeding cost confirmed at 1 fly per toad, the assumption every economy figure in this document has rested on since v0.1. Card holding limit confirmed as uncapped.

**v0.23 — 27 Aug 2026** — Tie-offs shortened to a single blind re-bid. Re-bids must now be **equal to or higher** than the tied amount rather than strictly higher, so no player is ever forced out by an inability to raise. This removes the deepest-purse-wins-by-attrition property: a rich player must now genuinely outbid to win a contested card, or lose it and 3 gold.

**v0.22 — 27 Aug 2026** — A player holding fewer than 3 gold cannot bid at all, making the minimum bid an eligibility requirement and guaranteeing that anyone who reaches a tie-off can pay the 3 gold penalty. Tie-offs now run up to three blind re-bids before the penalty lands, and end early if a tied player cannot or will not raise.

**v0.21 — 27 Aug 2026** — Bid ceiling confirmed as final after evaluating an overbid-penalty alternative. Rationale recorded: gold penalties are uncollectable from broke players, overbidding has no upside in blind mode, and is free griefing in live mode.

**v0.20 — 27 Aug 2026** — Granary and Larder names swapped so the larger card carries the larger name: Granary is now +8 flies, Larder +5. Added an open question on whether gold is public or hidden information, which bears directly on the bid ceiling.

**v0.19 — 27 Aug 2026** — Rotating recruitment order removed; recruitment is now a simultaneous secret declaration, making every phase but the auction fully simultaneous. The round's full auction slate is revealed face-up before bidding, then auctioned one card at a time in reveal order, turning the auction into a budgeting problem across the round. Auction format is now a game setting: `blind` (default) or `live` ascending. Confirmed no cap on properties per player, and that no player may bid above the gold they hold.

**v0.18 — 27 Aug 2026** — Low-count deck simplified: at 2 and 3 players every card is at 2 copies, giving a 36-card deck, with conditional scorers held at full strength. Corrected a long-standing arithmetic error: the deck has **18** card types, not 16 (the 51-card total was always right).

**v0.17 — 27 Aug 2026** — The "most gold" 5 VP end-game majority confirmed to stay. Toad supply uncapped. Each starved toad costs 1 happiness. Gold engine rates held at +3/+5. **Design considered feature-complete.**

**v0.16 — 27 Aug 2026** — War happiness penalty now applies only when the war has an actual winner. A tied war awards no token and costs no player happiness, creating a viable denial play.

**v0.15 — 27 Aug 2026** — Gold Seam raised to +3 gold and Deep Vein to +5 gold per round, putting the gold engines one step above their fly equivalents to compensate for gold having no direct VP value. Confirmed that every non-winner of the war loses 1 happiness, whether or not they fielded Military toads.

**v0.14 — 27 Aug 2026** — Rest majority bonus now escalates on a half-speed curve, increasing by 1 every other round: +1, +1, +2, +2, +3, +3.

**v0.13 — 27 Aug 2026** — Halfway bonus doubling removed. Majority bonuses and war token VP now follow the single escalation curve of `round + 1` for the whole game (2, 3, 4, 5, 6, 7). The war loss happiness penalty from v0.12 stands.

**v0.12 — 27 Aug 2026** — Majority bonuses now double from the halfway point of the game onward (rounds 4–6 in a 6-round game), on top of the existing per-round escalation. Every player who does not win the war loses 1 happiness that round.

**v0.11 — 27 Aug 2026** — Starting flies raised from 5 to 10 and starting happiness set at 10. Setup is now fully specified: 10 flies, 5 gold, 2 toads, 10 happiness.

**v0.10 — 27 Aug 2026** — Larder raised from +3 to +8 flies, making it the larger of the two fly instants and the biggest single resource grant in the deck.

**v0.9 — 27 Aug 2026** — Toad instants increased: Spawning Pool now grants 3 free toads, Tadpole Pond 2. Both resolve immediately, so the toads can be placed during Phase 3 of the round they are bought. All instant cards confirmed at a flat 2 VP.

**v0.8 — 27 Aug 2026** — Full property deck defined: 16 types, 51 cards. Engine cards flattened to 2 VP each. Instant cards doubled to two per effect category (Festival +5 / Public Park +3 happiness, Granary +5 / Larder +3 flies, Spawning Pool 2 / Tadpole Pond 1 toads). Conditional scoring cards at 2 copies each; everything else at 3.

**v0.7 — 27 Aug 2026** — Gold no longer converts to VP; it is an auction currency only. Happiness per-point VP removed, keeping only the 5 VP majority. Game-end tie-breaker reordered to toads first, then happiness. Starting resources set at 5 flies, 5 gold, 2 toads.

**v0.6 — 27 Aug 2026** — Added three end-game majority bonuses worth 5 VP each: most happiness, most gold, most flies. Ties award nothing, consistent with in-round majorities. Flies gain endgame value for the first time without scoring per unit.

**v0.5 — 27 Aug 2026** — Resource uses split hard: flies pay for toads and food only, gold pays for property only. No turn order in the game except toad recruitment, which uses a rotating player order. Majority bonuses now escalate by +1 per round from a base of +2. War token VP now escalates by +1 per round from a base of 2 VP. Starvation confirmed as a free player choice.

**v0.4 — 27 Aug 2026** — Happiness track floor moved from 0 to 1; zero is now unreachable, so every player can always recruit. This reverses the v0.3 hard block and removes the death-spiral risk. War ties award no token. Production rates set: Fields 2 flies/toad, Mine 2 gold/toad, Rest 1 happiness/toad. Majority bonuses set: Fields +2 flies, Mine +2 gold, Rest +1 happiness, all flat for the turn.

**v0.3 — 27 Aug 2026** — Happiness 0 now hard-blocks recruitment entirely rather than falling into the bottom cost band. Majority ties in a worker placement category award no bonus to anyone, with regular production still paid in full. War-tie handling flagged for confirmation.

**v0.2 — 27 Aug 2026** — Resolved auction format (one card at a time, silent simultaneous bid), auction tie resolution with 3-coin penalty and permanent card removal, final-round feeding confirmed, game-end tie-breaker (happiness then toads), flies confirmed as non-scoring, happiness bands set at 1–5 / 6–10 / 11–15 / 16–20, 2-player confirmed viable as-is. Majority-bonus tie-breaking remains open — it was raised but never settled.

**v0.1 — 27 Aug 2026** — Initial capture of core structure: four phases, happiness-gated recruitment, silent auction, hidden placement with harvest and war, feeding phase, VP scoring, first pass at card archetypes.
