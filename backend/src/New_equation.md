Great question — this is exactly the gap between a naive GBM simulator and a realistic market. Let me build the entire framework from first principles.Now I have everything needed. Let me build a deep, from-scratch explanation with an interactive visual.

The Problem: Why Pure GBM Is Blind to the Order Book
In standard GBM, the next price tick is computed purely from a random Wiener increment. It has no knowledge of whether 10,000 units are sitting on the bid side or whether the ask side is completely empty. In real markets, price formation is not a coin flip — it is the mechanical consequence of supply and demand physically colliding in the order book. The framework that formalizes this is called Order Flow Imbalance (OFI) price impact, formalized by Cont, Kukanov & Stoikov in the Journal of Financial Econometrics (2014), where they studied price impact of order book events using NYSE data for 50 U.S. stocks . Let's build it from zero.

Step 1: The Anatomy of a Limit Order Book
Before any equations, you need an exact mental picture of the LOB.
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) {
    animation-duration: 0.25s;
    animation-timing-function: cubic-bezier(0.19, 1, 0.22, 1);
  }
VvisualizeVvisualize show_widgetKey terms defined precisely:

Pb = best bid price (highest price a buyer is willing to pay)
Pa = best ask price (lowest price a seller is willing to accept)
Mid-price = (Pb + Pa) / 2 — the reference price GBM should track
Spread = Pa − Pb — the cost of an instant round-trip
Vb, Va = volume queued at the best bid and ask respectively
Depth D = Vb + Va — total liquidity at the top of the book

In the example above, buyers have 1200 units queued but sellers only have 300 at the best ask. Intuitively, the next aggressive market buy will wipe out all 300 ask units and push the price upward. GBM knows none of this.

Step 2: The Core Insight — Order Flow Imbalance (OFI)
The intuition behind price movement is an imbalance between supply and demand order flows. Cont et al. showed that over short time intervals, price changes are mainly driven by the order flow imbalance, defined as the imbalance between supply and demand at the best bid and ask prices. 
OFI is not simply Vb − Va. It is defined over a time interval [t−1, t] to capture the change in the best-level queues caused by order arrivals and cancellations. Here is the formal definition.
For a time interval [t−1, t], define four indicator events from the LOB:
Bid-side contribution eb:

If a new limit buy arrived at or above Pb(t−1): eb = +ΔVb (adds demand)
If Pb dropped (best bid moved down or was wiped): eb = −Vb(t−1) (demand destroyed)
If bid was unchanged: eb = ΔVb (quantity change at same price)

Ask-side contribution ea:

If a new limit sell arrived at or below Pa(t−1): ea = −ΔVa (adds supply, negative because it opposes buyers)
If Pa rose (ask moved away): ea = +Va(t−1) (supply disappeared, bullish)
If ask unchanged: ea = −ΔVa

OFI(t) = eb(t) − ea(t)
This gives a signed integer: positive OFI = more buying pressure, negative OFI = more selling pressure. It elegantly captures the net flow of aggressive intent at the best quotes.

Step 3: The Linear Price Impact Model
Cont, Kukanov & Stoikov reveal a linear relation between order flow imbalance and price changes, with a slope inversely proportional to the market depth. 
The model is:

ΔP(t) = β · OFI(t) + ε(t)

Where:

ΔP(t) = change in mid-price over interval [t−1, t]
β = price impact coefficient (sensitivity of price to imbalance)
OFI(t) = the order flow imbalance computed above
ε(t) = residual noise (mean zero)

And the key theoretical result: β ≈ 1/D, where D is the total depth at the best quotes. This makes perfect economic sense — if the book is deep (D is large), a given OFI barely moves the price. If the book is thin (D is small), even a small imbalance causes a large price jump. This is exactly the mechanism your PDF's GBM model ignores.

Step 4: The Full Coupled Model — OFI-Augmented GBM
Now we fuse the two. The pure GBM was:

dS = μS dt + σS dW

The OFI-coupled model replaces the drift term to make it dynamically depend on the live order book state:

dS = [μS + γ · OFI(t) / D(t)] dt + σ(t) · S · dW

Where:

γ = scaling parameter that converts OFI units into price-drift units (calibrated empirically, typically ~0.1 to 0.5)
D(t) = current total depth at best bid + ask (normalizes for liquidity)
σ(t) = can also be made state-dependent — e.g., σ · (1 + λ · |OFI(t)|/D(t)), so volatility increases when the book is imbalanced

In discrete simulation (which is what you need for Project Synthetic-Bull), this becomes:

S(t+Δt) = S(t) · exp[(μ − σ²/2)Δt + σ√Δt · Z + γ · OFI(t)/D(t) · Δt]

where Z ~ N(0,1) is the random shock. The OFI term inside the exponent nudges the price path in the direction of the net order pressure each tick.

Step 5: Weighted Mid-Price — A Simpler Variant
A closely related and very practical idea is the Weighted Mid-Price (WMP). Instead of tracking the raw mid-price (Pa + Pb)/2, you weight it by the relative depth on each side:

WMP = Pb · (Va / D) + Pa · (Vb / D)

Think about what this does: if the ask side is thin (Va is small), the weighted mid-price gets pulled toward the ask — it anticipates upward pressure. Using probabilities of bid and ask states, this model of price dynamics has both drift and volatility driven by volume imbalance, and naturally generates higher kurtosis and heavier-tailed distributions compared to standard GBM with constant volatility — the drift term emerges as a consequence of order book imbalance.  The WMP is a zero-lag, instantaneous approximation of the OFI model and is often used as the "true price" signal in practice.

Step 6: Interactive Demonstration
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) {
    animation-duration: 0.25s;
    animation-timing-function: cubic-bezier(0.19, 1, 0.22, 1);
  }
VvisualizeVvisualize show_widgetTry dragging the "Bid volume" slider to 3000 while keeping "Ask volume" at 300. You'll see the OFI-augmented green line diverge strongly upward from the flat dashed GBM — that is exactly the price impact of a thin ask side being overwhelmed by bid pressure.

Step 7: How to Implement This in Project Synthetic-Bull
Here is the precise engineering recipe to couple your GBM with the order book:
Every tick (say every 100ms):

Read the current best bid/ask state from your LOB: Vb_curr, Va_curr, Pb_curr, Pa_curr
Compute OFI from the delta since the last tick:

   eb = (Pb_curr >= Pb_prev) ? Vb_curr - Vb_prev : -Vb_prev
   ea = (Pa_curr <= Pa_prev) ? Va_curr - Va_prev : +Va_prev
   OFI = eb - ea

Compute depth-normalized imbalance: I = OFI / D where D = Vb_curr + Va_curr
Evolve the reference price using the augmented GBM:

   S_new = S_old * exp((μ - σ²/2)*Δt + σ*√Δt*Z + γ*I*Δt)

Use S_new as the new mid-price target for your synthetic market generator. It now submits new bids and asks centered around this price, which changes the book, which changes OFI next tick — creating a live feedback loop.

The key parameters to tune for realism are γ (impact strength, try 0.2–0.5) and how you compute OFI — using only the best level (Level 1) is simplest, but multi-level OFI integrates OFIs at the top levels of the limit order book into a single variable that better explains price impact compared to best-level OFI alone. 
This transforms your simulator from a decoupled GBM machine into a genuine microstructure-aware exchange — exactly the kind of depth that would distinguish a top entry in this competition.