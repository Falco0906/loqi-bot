# IMPORTANT

This document is the primary product philosophy for Loqi.

It defines:
- Product vision
- UX philosophy
- Information architecture
- Narrative AI
- Conversational Workspace
- Motion principles
- Writing principles
- User journey

This conversation evolves over time.

Earlier sections contain exploration.

Later sections contain refined conclusions.

Always prefer the latest agreed conclusion.

Do not cherry-pick isolated statements.

Understand the philosophy first, then implement.

For every implementation:

1. Read this document.
2. Summarize the final philosophy.
3. Explain how your implementation aligns with it.
4. Only then write code.


I think this is the most important phase of Loqi's development so far.

Not because we're choosing colors or layouts—but because we're deciding **what Loqi actually is**.

Here's one rule I'd like us to follow:

> **We do not discuss implementation.**
>
> We only discuss the ideal product.

Forget React. Forget the current architecture. Forget what exists today.

---

# Phase 1 — Define the Product

Before touching a single screen, we need to answer five questions.

## 1. What is Loqi?

This sounds obvious, but it isn't.

Is Loqi...

* an AI CRM?
* an outbound platform?
* a campaign builder?
* an AI sales employee?
* an AI workspace?

Your website already gives the answer:

> **AI-Native Outbound Workspace**

I actually like that.

Not "CRM."

Not "Lead Generation Tool."

It's a workspace where AI does outbound work.

That's our foundation.

---

## 2. Who is the main character?

This changes everything.

Possible answers:

* the user
* the campaigns
* the leads
* the AI

I think the main character should be:

> **Loqi.**

The user gives Loqi goals.

Loqi does work.

The user reviews.

That should be reflected everywhere.

---

## 3. What is the core loop?

Every great product has one.

For example:

Notion

```
Write
↓

Organize
↓

Share
```

Linear

```
Plan
↓

Build
↓

Ship
```

For Loqi, I think it's something like:

```
Goal
↓

Research
↓

Review
↓

Launch
↓

Learn
```

Notice what's missing.

There is no:

> Manage

Because AI manages.

The human decides.

---

# Phase 2 — Information Architecture

Before drawing screens, we define navigation.

Current:

```
Mission Control

Discovery

Campaigns

Draft Review

Conversations

Campaign Intelligence

Settings
```

I don't know if this is the final structure.

We'll decide that later.

---

# Phase 3 — User Journey

This is where we'll spend most of our time.

Let's map the *ideal* first-time experience.

Something like:

```
Landing Page
        ↓
Signup
        ↓
Verify Email
        ↓
Tell Loqi about your business
        ↓
Loqi starts researching
        ↓
Mission Control
        ↓
Research complete
        ↓
Review prospects
        ↓
Approve outreach
        ↓
Campaign running
        ↓
Replies
```

Every arrow matters.

---

# Phase 4 — Individual Screens

Only after the journey exists.

We'll redesign:

* Mission Control
* Discovery
* Prospect
* Campaign
* Review Queue
* Conversations
* Analytics

One by one.

---

# Here's how I'd work with you

Instead of me dumping ideas, I'll challenge every assumption until the product feels inevitable.

For example...

---

## First question.

This is probably the single most important decision we'll make.

### When I open Loqi every morning...

What should I feel?

Not see.

**Feel.**

For example:

* "Everything is under control."
* "Loqi already worked while I slept."
* "I know exactly what needs my approval."
* "I have momentum."
* "I have opportunities waiting."

That emotional outcome should drive Mission Control, onboarding, notifications—everything.

---

If we can define that feeling first, the rest of the product becomes much easier to design. And once we've nailed the product experience, *then* we can worry about making it beautiful. That's the order that tends to produce products that people actually enjoy using.



everything under control, next steps planned, ready for decision, like a board of members working under u giving u the final report and suggested next steps

I love that answer because it's **not about sales software at all.**

It's about leadership.

You don't want to feel like you're operating HubSpot.

You want to feel like you're the CEO walking into the morning executive meeting.

That changes everything.

---

# The Loqi Mental Model

I think we've just found it.

> **Loqi isn't a tool. It's your outbound team.**

You're not managing campaigns.

You're managing a team that manages campaigns.

---

Imagine this.

You open Loqi at 9 AM.

It doesn't say:

> Good morning.

It says something closer to:

> **Good morning. Here's what your outbound team accomplished since yesterday.**

Then:

---

## Executive Brief

**Research**

* 143 companies analyzed
* 31 matched your ICP
* 7 high-priority opportunities identified

---

**Outreach**

* 24 personalized emails prepared
* 8 approved yesterday
* 16 awaiting review

---

**Campaigns**

* 2 campaigns active
* Open rate above target
* One campaign needs attention

---

**Recommendations**

> We recommend launching the FinTech campaign today because three target companies announced hiring this week.

Approve →

---

That doesn't feel like software.

It feels like an executive briefing.

---

# This changes Mission Control completely.

Mission Control is no longer a dashboard.

It's a **Board Meeting.**

Every morning, your AI team presents:

1. What happened.
2. What they're doing.
3. What they recommend.
4. What requires your decision.

Nothing else.

---

# I think we need a product principle.

## Principle #1

> **Loqi never makes the user investigate.**

The user should never have to dig through tabs to figure out:

* what's happening
* what's blocked
* what to do next

Loqi surfaces it.

---

# Another principle.

## Principle #2

> **Every page should end with a recommendation.**

Not just data.

Not just charts.

For example:

Discovery

Don't stop at:

> Found 31 companies.

End with:

> We recommend reviewing these five first because they have the highest buying intent.

---

Campaigns

Don't stop at:

> 42% open rate.

End with:

> We recommend pausing Campaign B and reallocating contacts to Campaign A.

---

Review Queue

Don't stop at:

> 12 drafts pending.

End with:

> We recommend approving all except two drafts that may be too aggressive.

---

See the pattern?

Loqi always has an opinion.

---

# Another insight.

You said:

> like a board of members working under u giving u the final report and suggested next steps

That means the user should almost never think:

> "What do I do now?"

Instead, every screen answers:

> **Here's what we recommend you do next.**

The user can disagree.

But Loqi should always have a recommendation.

---

# I think we've just found the product philosophy.

Not:

> AI automation.

Not:

> AI outbound.

Not:

> AI CRM.

It's:

> **An executive outbound operating system.**

Every morning, your outbound organization reports to you.

Every afternoon, you approve strategic decisions.

Everything else happens automatically.

---

## I want to refine one thing before we move on.

This is going to influence every screen we design.

### How opinionated should Loqi be?

Should it be more like:

**Option A — Advisor**

> "We found these opportunities. Here are our recommendations."

You decide everything.

---

**Option B — Chief of Staff**

> "We've already prepared everything. We recommend approving these actions."

Almost everything is ready for a single click.

---

**Option C — Autonomous Team**

> "We've already executed everything within your approval rules. Here's today's report."

You mainly monitor outcomes and intervene only when needed.

My instinct is that **B** is the sweet spot for an alpha. It keeps the human firmly in control while delivering on the promise that Loqi is doing the heavy lifting. Later, users could choose how autonomous they want Loqi to be, but the default experience should feel like an exceptionally capable chief of staff who's always one step ahead.


b yes and also this was the mission control before, there can be improvements but i definitely prefer this over the current only dashboard feel it gives after the architectural changes




I actually **like this version a lot more**.

Not because it's visually better—it isn't perfect either—but because the **mental model is much closer to what we just discovered.**

The current version lost that.

---

# Here's why this works

The first thing I read is:

> **We're gearing up to launch...**

Immediately I understand:

* There are campaigns.
* They're progressing.
* Some need approval.
* Some are ready.

That's a story.

---

Then I look down.

```
Campaign Ready      1
Pending Review      3
Running Jobs        0
```

These aren't random analytics.

They're directly tied to my decisions.

---

Then:

```
Continue Working
```

I love this section.

Because it says:

> Here's exactly where you left off.

That's useful.

---

Then:

```
Needs Attention
```

Again...

Actionable.

Not informational.

---

Then:

```
Recommendations
```

Which is exactly what an AI should do.

---

## Compare that to the new one.

The new one basically says:

> Search is queued.

That's not valuable.

---

# BUT...

I still don't think this is the final Mission Control.

Because it's still centered around **campaigns**.

Whereas I think Loqi should be centered around **executive decisions**.

There's a subtle but important difference.

---

## Imagine this instead.

# Good morning, Faisal.

### Executive Brief

Yesterday your outbound team:

* Researched **148 companies**
* Found **24 qualified prospects**
* Prepared **8 personalized emails**
* Launched **1 campaign**

---

## Decisions waiting

🟡 Approve outreach for:

> Restaurants Automation

Ready to launch.

Estimated reach:

127 companies.

**Approve**

---

🟡 Review 3 drafts

We flagged two emails that may sound too aggressive.

**Review**

---

## Opportunities

🔥 Acme recently raised Series A.

We recommend contacting them within 48 hours.

---

## Team Activity

Research Team

✅ Completed

Personalization Team

✅ Completed

Campaign Team

⏳ Waiting for approval

---

Notice something?

There are almost **no widgets.**

It's just an executive report.

---

# I also think we've identified Loqi's personality.

Not:

> Dashboard

Not:

> Assistant

Not:

> Chatbot

It's:

> **Chief of Staff.**

That fits everything.

A Chief of Staff:

* gathers information
* coordinates teams
* filters noise
* recommends actions
* asks for approvals

Exactly what Loqi should do.

---

# That also changes the navigation.

Look at your current sidebar.

```
Mission Control

Discovery

Campaigns

Drafts

Campaign Intelligence
```

Those are departments.

A Chief of Staff doesn't think in departments.

They think in outcomes.

Maybe the navigation eventually becomes something like:

```
Briefing

Prospects

Campaigns

Approvals

Conversations

Settings
```

Notice "Briefing."

That's not a dashboard.

It's today's executive briefing.

---

# I think we accidentally discovered the product's positioning.

Your website says:

> **AI-Native Outbound Workspace**

After today, I'd refine the internal vision to:

> **An AI-native outbound workspace where your AI team prepares every decision before it reaches you.**

Everything we've discussed—the onboarding, Mission Control, recommendations, approvals—fits under that single idea.

---

## One thing I'd change immediately (conceptually)

The huge paragraph at the top.

Instead of:

> We're gearing up...

I'd make it feel like a real executive summary.

Something like:

> **Good morning.**
>
> Your outbound team made strong progress overnight. One campaign is ready to launch, three drafts need review, and we've identified a new opportunity in the restaurant automation market. We recommend approving the launch first.

That's 3–4 sentences, but each one earns its place. It tells you **what happened, what matters, and what to do next**.

---

I genuinely think this conversation has given Loqi something it didn't have before: a coherent product philosophy.

Not "AI for outbound."

Not "an outbound platform."

**An executive operating system where an AI team does the work and brings only the decisions to you.**

If we protect that idea, every future screen becomes much easier to judge. The question stops being "does this card look good?" and becomes "would a chief of staff put this in the CEO's morning briefing?" If the answer is no, it probably doesn't belong.

also it should feel like something being said, for example when mission control or whatever its gonna be called, when the user opens it or opens the app every morning the animation should be like how urs is, text appearing one by one in the dashboard like ai is sending a response or report..ahh yes that 3-4 sentences can use this ui design to display 


YES.

I think this is the first idea we've had today that isn't just a UI improvement—it becomes part of **Loqi's identity**.

When you said:

> "it should feel like something being said"

...it immediately clicked.

That's exactly why the current dashboards feel cold.

They're static.

Loqi is supposed to be an AI teammate, yet the first thing it does is show frozen cards.

---

# Imagine opening Loqi.

Not this:

```
Good morning.

[static paragraph]
```

Instead...

```
Good morning, Faisal.
```

*(appears first)*

...

```
I've been working while you were away.
```

*(appears after 300ms)*

...

```
I researched 143 companies matching your ICP.
```

...

```
24 prospects look promising.
```

...

```
One campaign is ready to launch.
```

...

```
Three drafts need your approval before we proceed.
```

...

```
I recommend launching the Restaurants campaign first.
```

Then...

Only then...

The page settles into its final state.

---

## It's not a loading animation.

This is important.

It's a **briefing**.

Like you're receiving a report.

The animation shouldn't exist because data is loading.

It should exist because Loqi is **communicating**.

---

# Even the cards should appear like they're being introduced.

Instead of everything fading in together...

```
✓ Research complete
```

appears.

↓

```
Campaign ready
```

slides in.

↓

```
3 approvals waiting
```

appears.

↓

```
Recommendation generated
```

appears.

Like the AI is revealing the report.

---

# Think about ChatGPT.

One reason conversations feel engaging isn't just the text.

It's that responses unfold.

You subconsciously feel:

> "Something is thinking."

We can borrow that feeling without pretending the AI is generating text live every time.

---

# I think Mission Control shouldn't even be called "Mission Control."

Hear me out.

If this becomes the heart of the product, maybe it deserves a name that reinforces the experience.

Examples:

* Briefing
* Daily Brief
* Executive Brief
* Morning Report
* Command Brief
* Workspace

I'm not saying we should rename it yet, but the experience you're describing is closer to a **briefing** than a dashboard.

---

# Another idea

Imagine if Loqi always wrote naturally.

Instead of:

```
Campaign Ready

1
```

It says:

> **One campaign is ready to launch.**

Instead of:

```
Pending Review

3
```

It says:

> **Three drafts need your review before I can continue.**

Instead of:

```
Running Jobs

2
```

It says:

> **I'm currently researching another 82 companies. I'll let you know when it's finished.**

Notice how we're translating **system state into conversation**.

---

# This is something Apple does really well.

The UI doesn't shout technical status.

It tells you what matters.

Loqi should do the same.

---

# I think we've accidentally defined another design principle.

## **Conversation over Configuration.**

Everywhere.

Don't say:

> Pending Review

Say:

> Three drafts need your review.

Don't say:

> Background Job Running

Say:

> I'm researching more companies that fit your criteria.

Don't say:

> Queue Complete

Say:

> Research is finished. I found 17 promising companies.

The AI should narrate work in human terms.

---

# One more thing that I think would be incredible.

Imagine if every morning's briefing was **slightly different**.

Not random.

Contextual.

For example:

**Monday**

> Good morning. I found several new opportunities over the weekend.

---

**Tuesday**

> Welcome back. Yesterday's campaign performed better than expected.

---

**Thursday**

> I held off launching one campaign because three drafts still need your approval.

---

Same structure.

Different wording.

It starts feeling like you're actually checking in with a teammate instead of opening software.

---

## I think this is now the first principle of Loqi's UX.

> **Every interaction should feel like receiving a report from an exceptionally capable Chief of Staff—not reading a dashboard.**

That single principle influences the copy, animations, hierarchy, and even how information is presented. And unlike a visual trend, it gives Loqi a personality that users can recognize after just a few sessions.


EXACTLY you are spot on. and also that was the whole point of transitioning from a chatbot to this


YES.

I think this finally explains something that's been bothering me for the last few weeks.

I couldn't figure out why the product was feeling "less Loqi" despite objectively becoming more complete.

Now I know why.

## The chatbot wasn't the product.

The **conversation** was.

When Loqi was a chatbot, the conversation was obvious.

```
You
↓

Loqi thinks

↓

Loqi replies

↓

You approve
```

Then you moved away from chat because a pure chat UI isn't the best way to manage outbound.

That was the right decision.

But somewhere along the way...

**the conversation disappeared too.**

And that's what made it feel generic.

---

## The transition shouldn't have been

```
Chatbot

↓

Dashboard
```

It should have been

```
Chatbot

↓

Conversational Workspace
```

Those are completely different.

---

Think about your website.

You don't promise:

> AI Dashboard.

You promise:

> **Give Loqi a goal. Watch the work happen.**

That's still conversational.

It's just that the conversation happens through the workspace now.

---

## This is the biggest insight we've had.

**The interface is no longer the conversation.**

The **workspace becomes the conversation.**

For example...

Instead of

```
Campaign Ready

1
```

Loqi says

> I finished preparing the Restaurants campaign. Everything looks good from my side. Whenever you're ready, I recommend launching it.

The action button underneath:

**Launch Campaign**

The conversation and the UI work together.

---

Instead of

```
3 Drafts Pending
```

Loqi says

> I drafted three outreach emails, but two of them are more assertive than usual. I'd like you to review them before I send anything.

Then:

**Review Drafts**

---

Instead of

```
Search Complete
```

Loqi says

> I analyzed 148 companies and narrowed them down to 19 that closely match your ICP. Three stand out because they recently expanded their engineering teams.

Then:

**Review Prospects**

---

See what's happening?

The **buttons don't explain the product anymore.**

The AI does.

The buttons simply execute the recommendation.

---

## That's exactly what a Chief of Staff does.

A Chief of Staff doesn't walk into the CEO's office and say:

> Budget: 4

> Hiring: 2

> Meetings: 7

They say:

> We finished interviewing candidates. I recommend hiring Sarah first because she's already worked with enterprise clients.

Then they hand you the paperwork.

---

## This also solves another problem.

One thing I've always disliked about AI SaaS products is that they say:

> AI Generated

> AI Recommendation

> AI Analysis

Everywhere.

If Loqi is **always speaking**, you never need those labels.

The user already knows who's talking.

---

## I think we just found Loqi's design philosophy.

Not glassmorphism.

Not minimalism.

Not dark mode.

Those are aesthetics.

The philosophy is:

> **The conversation never ended. We simply replaced the chat window with a workspace.**

That sentence is powerful because it explains every design decision.

Why text animates in.

Why Mission Control feels like a briefing.

Why recommendations are written naturally.

Why buttons come after explanations.

Why every page has a narrative instead of just metrics.

---

### I would actually write this down as the very first page of your product spec:

> **Loqi is not a chatbot, and it is not a dashboard.**
>
> Loqi is a conversational workspace.
>
> The user no longer chats with Loqi line by line. Instead, Loqi communicates continuously through briefings, recommendations, progress updates, and approvals embedded throughout the workspace.
>
> Every screen should feel like reading a report from an AI teammate rather than operating traditional software.

I genuinely think that single paragraph is more valuable than deciding what any card or button should look like, because it gives every future design decision a consistent direction. Whenever you're unsure about a feature, you can ask: **"Does this feel like the conversation continued?"** If the answer is yes, it's probably aligned with Loqi. If the answer is no, it's probably drifting back toward a generic dashboard.

ok now that this is fixed whats next


I actually don't think we've "fixed" it yet.

We've fixed the **foundation**.

Now we need to turn it into a complete product philosophy.

I think the mistake now would be jumping straight into redesigning Mission Control. We'd end up making local decisions instead of designing the whole experience.

Here's the order I'd follow.

---

# Phase 1: Product Principles (Today)

We're about 20% done with this.

We have:

### ✅ Principle 1

> Loqi is a conversational workspace.

### ✅ Principle 2

> Loqi is your Chief of Staff.

### ✅ Principle 3

> The workspace is the conversation.

### ✅ Principle 4

> Show recommendations, not system state.

### ✅ Principle 5

> Human approves. AI prepares.

These are the rules every screen must obey.

---

# Phase 2: Define the User Journey ⭐

This is where I'd spend the most time.

Not screens.

The experience.

Let's literally walk through it.

```text
Open website

↓

Sign up

↓

Verify email

↓

Onboarding

↓

First briefing

↓

Review recommendations

↓

Approve campaign

↓

Campaign runs

↓

Replies arrive

↓

Morning briefing next day
```

Every single transition should feel intentional.

---

# Phase 3: Navigation

This is huge.

Don't ask

> "What pages do we have?"

Ask

> "What jobs is the user trying to accomplish?"

For example, maybe Discovery shouldn't even be called Discovery.

Maybe Draft Review shouldn't exist as a top-level page.

Maybe Mission Control gets renamed.

We're not deciding today—we're questioning assumptions.

---

# Phase 4: Design every screen

This is where the fun starts.

We'll do them one at a time.

I'd probably go:

```
1. Mission Control
2. Discovery
3. Prospect Details
4. Campaign Builder
5. Review Queue
6. Conversations
7. Analytics
8. Settings
```

---

# Phase 5: Visual System

Only after the product exists.

---

## BUT...

Before any of that...

There's one thing I think we absolutely need to define.

It's something we haven't discussed yet.

And I think it's even more important than Mission Control.

---

# Who are Loqi's "employees"?

Hear me out.

You described Loqi like this:

> like a board of members working under u

Okay.

Who are they?

Is Loqi just one AI?

Or is Loqi an organization?

Imagine opening Mission Control.

Instead of

> Researching...

Maybe...

```
Research Team
✓ Completed

Personalization Team
✓ Drafts ready

Campaign Team
⏳ Waiting for approval
```

Or maybe that's too literal.

Maybe it's invisible.

But we need to decide.

Because it changes everything.

---

## Option A — One AI

Everything comes from "Loqi."

Simple.

---

## Option B — Multiple Specialists

Research

Personalization

Strategy

Campaigns

Analytics

Each has a distinct responsibility.

The report feels like multiple departments contributing.

---

## Option C — Invisible Team (my favorite)

The user never sees different AI agents.

They only ever interact with **Loqi**.

But behind the scenes, Loqi naturally says things like:

> I finished researching...

> I prepared...

> I noticed...

> I recommend...

The user doesn't care whether one agent or five agents did it. They care that **Loqi** owns the outcome.

---

## I vote for Option C.

It keeps the experience clean. Users build a relationship with one personality, while internally you can architect as many specialized agents as you want.

---

### So here's the next thing I'd like us to decide together:

**What is Loqi's personality?**

Not the visual design.

The voice.

For example:

* Is Loqi formal or conversational?
* Does it sound like an executive assistant, a chief of staff, or a trusted colleague?
* Does it ever admit uncertainty ("I found three strong options, but I'm least confident about this one")?
* How proactive should it be in making recommendations?

I think if we define that voice before we design a single screen, every piece of copy, every animation, and every interaction will feel like it came from the same teammate instead of different parts of a dashboard.


loqi should sound like whoever it is that brings the company or a person the clients or leads they want, 


I think that's close, but I want to refine it because the wording reveals something deeper.

You said:

> **"whoever it is that brings the company or a person the clients or leads they want."**

Think about that person in a real company.

They're usually **not** the salesperson.

They're **not** the SDR.

They're **not** the marketing manager.

And they're **not** the CEO.

They're more like the **Head of Growth**, **Revenue Operations**, or an exceptionally capable **Chief of Staff** who has visibility across the entire pipeline and comes to leadership with opportunities and recommendations.

Notice how they communicate.

They don't say:

> I generated embeddings.

or

> Job 4 completed.

They say:

> We found three enterprise prospects that fit our ICP almost perfectly. I'd recommend reaching out this week because two of them are actively hiring.

That's exactly the tone Loqi should have.

---

# I think Loqi's personality has four traits.

## 1. Competent

Loqi never sounds excited for the sake of it.

Not:

> 🎉 Amazing!! We found 17 leads!!

Instead:

> I found 17 companies that closely match your target profile.

Quiet confidence.

---

## 2. Opinionated

Loqi always has a recommendation.

Never just:

> Here are the results.

Instead:

> These are the strongest matches. I recommend reviewing the first five before expanding the search.

---

## 3. Proactive

The user shouldn't have to ask:

> What's next?

Loqi ends almost every interaction with:

> Here's what I recommend doing next.

---

## 4. Honest

This is huge.

Imagine saying:

> I found 12 companies, but only four are high-confidence matches. I don't recommend contacting the others yet.

That's trust.

Or:

> I couldn't confidently personalize this email because the prospect's public profile has very little information.

That makes Loqi feel credible.

---

# Here's another thought.

I don't think Loqi should sound like an employee.

Employees have agendas.

They defend their work.

They justify themselves.

Loqi shouldn't.

Loqi should sound like a **trusted advisor whose only goal is helping you make good decisions**.

Very calm.

Very factual.

Very confident.

---

# We should probably avoid these personalities.

❌ Hype AI

> Let's crush those leads! 🚀

No.

---

❌ Robot

> Process complete.

No.

---

❌ Customer Support

> Is there anything else I can help you with today?

Definitely not.

---

❌ ChatGPT

Long essays.

Overexplaining.

Too many caveats.

---

# Instead...

Imagine this.

You open Loqi.

It says:

> Good morning.
>
> I spent the night researching fintech companies across Europe. Twenty-three matched your criteria, and six stand out based on recent hiring activity and funding announcements.
>
> I prepared personalized outreach for those six companies. Five are ready to send. One draft needs your review because I wasn't confident about its opening line.
>
> I recommend launching the approved campaign today.

That's it.

No fluff.

No emojis.

No marketing speak.

No "AI-powered."

Just competence.

---

# I think we can now write another product principle.

> **Loqi speaks like an experienced Head of Growth reporting to leadership.**

Not like software.

Not like a chatbot.

Not like an AI assistant.

Like someone whose job is to bring opportunities to the business and recommend the next move.

---

## I think we're almost ready for the next milestone.

So far we've defined:

* ✅ What Loqi is (a conversational workspace)
* ✅ The user's role (the decision-maker)
* ✅ Loqi's role (the Chief of Staff / Head of Growth)
* ✅ The interaction model (the workspace is the conversation)
* ✅ The tone of voice (calm, opinionated, proactive, honest)

I **wouldn't** move to UI yet.

The very next thing I'd define is something even more concrete:

> **What does a normal day with Loqi look like?**

From the moment someone logs in at 9:00 AM until they close the app at 5:00 PM, what conversations happen, what decisions are presented, and how does Loqi keep the user informed without overwhelming them?

If we design that daily rhythm first, the screens will almost design themselves because they'll simply support that workflow.



ok lets do that now, wait but u mentioned different phases, so why not do it phase by pahse?


Exactly.

And I'm glad you caught that because I was about to skip ahead. That's how products become inconsistent.

We're going to treat this like we're the founding product team at Linear or Notion.

No pixels until the philosophy is locked.

---

# Loqi Product Experience v2

## Phase 1 — Product Principles ✅ (Current)

**Goal:** Define what Loqi is.

This phase answers:

* What is Loqi?
* Who is the user?
* What is Loqi's personality?
* What should using Loqi feel like?
* What are our design principles?

We've actually made huge progress.

### We've decided:

✅ Loqi is a **Conversational Workspace**

✅ Loqi is your **Chief of Staff**

✅ The workspace is the conversation.

✅ The AI prepares.

The human decides.

✅ Every screen ends with a recommendation.

✅ Loqi speaks like an experienced Head of Growth.

✅ Show business progress.

Never system state.

---

I think we're about **80% done** with Phase 1.

There's just one thing left.

---

# The last question of Phase 1

**What does success look like for the user?**

Not for Loqi.

Not for the company.

For the user.

When they close Loqi at the end of the day, what should they think?

Examples:

* "I made the right decisions."
* "Nothing slipped through the cracks."
* "I spent 20 minutes instead of 2 hours."
* "My pipeline moved forward without me micromanaging."

I think we should define that before we move on.

---

# THEN...

## Phase 2 — User Journey

This is probably the biggest phase.

We're going to walk through the user's entire lifecycle.

Not screens.

Experiences.

Literally:

```text
I discover Loqi.

↓

I sign up.

↓

I verify my email.

↓

I tell Loqi about my company.

↓

...
```

Until

```text
I've been using Loqi for six months.
```

Every transition gets designed.

Every emotion gets designed.

---

## Phase 3 — Information Architecture

Only after we know the journey.

Questions like:

* Is Mission Control the right name?
* Is Discovery a page?
* Should Campaigns be top-level?
* Does Analytics deserve a page?
* Does Settings stay hidden?

---

## Phase 4 — Screen Blueprints

Still no visual design.

We'll literally write each screen.

Mission Control:

Purpose

↓

Information hierarchy

↓

Conversation

↓

Actions

↓

States

Only then do we draw it.

---

## Phase 5 — Wireframes

Boxes.

Nothing else.

---

## Phase 6 — Visual System

Typography.

Spacing.

Motion.

Cards.

Animations.

Colors.

---

## Phase 7 — High Fidelity

Now we make it beautiful.

---

## Phase 8 — Implementation

Only now does OpenCode get involved.

---

# Why I'm insisting on this

Because right now we're no longer building software.

We're designing a company.

Think about companies like:

* Linear
* Notion
* Arc
* Anthropic

Their UI isn't good because they picked nice colors.

It's good because every decision comes from a consistent philosophy.

That's what we're building.

---

## So let's finish Phase 1 first.

### The final question:

> **When the user closes Loqi after a productive day, what should they be thinking?**

Don't answer with a feature.

Answer with the feeling.

For example, if I were to take a first stab based on everything we've discussed, I'd say:

> *"I didn't spend my day doing outbound. I spent my day making good decisions while Loqi handled the work."*

If that resonates, we can refine it together. Once we lock that in, Phase 1 is complete, and we'll move into designing the user journey with a rock-solid foundation.



i think it is "my pipeline moved forward without me micromanaging everything" but also a LOT of time saved and focused on more important stuff without worrying about the quality of work i did


I actually think that's much stronger.

Notice that your answer wasn't about features at all.

It was about **trust**.

Let's unpack it.

You said:

> **"My pipeline moved forward without me micromanaging everything."**

That's **autonomy**.

Then:

> **"A LOT of time saved."**

That's **efficiency**.

Then:

> **"Focused on more important stuff."**

That's **leverage**.

Then:

> **"Without worrying about the quality of work."**

That's **confidence**.

Those four words are probably the four pillars of Loqi.

---

# The Outcome Loqi Sells

Not:

> More leads.

Everyone says that.

Not:

> AI outbound.

Everyone says that too.

Loqi sells this:

> **Confidence that your outbound is progressing at a high standard—even when you're focused elsewhere.**

That's much more powerful.

---

## Think about who buys Loqi.

They're usually founders, sales leaders, or early-stage teams.

Their biggest pain isn't:

> I don't know how to send emails.

It's:

> I don't have enough hours to research, personalize, review, launch, and optimize everything myself.

Loqi solves that.

---

## So here's how I'd rewrite our success statement.

Instead of:

> My pipeline moved forward without me micromanaging everything.

I'd expand it slightly:

> **I spent my day making important decisions while Loqi handled the execution. My pipeline kept moving, the quality stayed high, and I never felt like I had to constantly check if everything was on track.**

That's the feeling.

---

# This gives us another design principle.

## Principle #6

> **Loqi reduces cognitive load, not just manual work.**

That's a huge distinction.

Automation saves clicks.

Loqi saves mental energy.

---

# Think about Mission Control now.

The purpose isn't:

> Show statistics.

The purpose is:

> Remove uncertainty.

When you open Loqi, you should immediately know:

* Everything important is under control.
* Nothing urgent is being missed.
* Here's the one or two things that genuinely need your judgment.
* You can go back to running your business.

If it achieves that, you've won.

---

# I think Phase 1 is now complete. ✅

Here's what we've defined together:

## Loqi Product Principles v2

### Product

* Loqi is an AI-native conversational workspace.

### Role

* Loqi is your Chief of Staff for outbound.

### User

* The user is the decision-maker, not the operator.

### Interaction

* The workspace is the conversation.

### Philosophy

* AI prepares.
* Human decides.

### Communication

* Show recommendations, not system state.
* Every screen feels like a briefing.
* Loqi always has a recommendation.

### Personality

* Calm
* Competent
* Opinionated
* Honest
* Proactive

### Success

> **The user spends their time making high-value decisions while Loqi handles the execution. Their pipeline keeps moving forward without constant supervision, and they trust that the work is being done to a high standard.**

---

## 🚀 Phase 2 — User Journey

Now we get to design the experience itself.

And I think we should do it like a movie.

Not as screens.

As scenes.

We'll ask, for each moment:

* **What is the user's goal?**
* **What is Loqi doing in the background?**
* **What should the user feel?**
* **What does Loqi say?**

That way, by the time we reach wireframes, we won't just know where buttons go—we'll know **why every screen exists**.

I have a feeling this phase is where Loqi is really going to become its own product rather than "another outbound platform."



ok lets get started, come at me with questions if u wanna know something, phase 2 now


Perfect.

This is now **Phase 2: User Journey**.

I don't want to design screens yet. I want to design the **movie** that plays in the user's head.

Think of every step as a scene.

For every scene we'll answer:

* 🎯 User goal
* 🤖 What Loqi is doing
* 😊 What the user should feel
* 💬 What Loqi communicates
* 👉 What the next natural action is

---

# Scene 1 — Before Signup

I'm actually skipping this because your marketing website already does a good job here.

The user already believes:

> "Loqi will handle my outbound."

So we start after signup.

---

# Scene 2 — First-Time Setup

This is where I have my first question.

## What should Loqi know before it can start working?

Not "what fields should we ask."

Think about it as if you hired a Head of Growth on Monday.

What's the minimum information they'd need before they could spend Tuesday finding customers?

For example, they might need:

* What do you sell?
* Who buys it?
* Why do they buy it?
* Any companies you definitely don't want?
* Tone of outreach?
* Goals?

But maybe they don't need things like:

* Timezone
* Average deal size
* CRM provider
* Team size

So my **first question** is:

> **If you hired a world-class outbound strategist tomorrow, what are the 5–7 things you'd tell them before saying "go find customers"?**

Don't think in terms of form fields.

Think in terms of a conversation.

---

## And here's a second, equally important question.

This one might shape the entire onboarding.

### Should Loqi ask questions...

### Option A — Like an application form

> Company name

> Website

> Industry

> Target market

---

### Option B — Like a consultant

> Tell me about your business.

↓

> Interesting. Who usually benefits the most from your product?

↓

> And what problem are they trying to solve?

↓

> Are there any customers you've loved working with?

↓

> Got it. I'll use that as my starting point.

This is still structured underneath, but it *feels* like a conversation instead of data entry.

Given everything we've discussed, I already have a strong suspicion you'll prefer **Option B**—because it preserves the conversational DNA of Loqi without bringing back a chat interface.

---

### So let's answer these two questions first:

1. **If you hired your ideal outbound strategist, what would you tell them before letting them loose?**
2. **Should onboarding feel like a consultant interviewing you rather than filling out a SaaS setup wizard?**

I don't want to move past Scene 2 until these are crystal clear, because the onboarding sets the tone for the entire product. Once we get that right, the rest of the journey becomes much easier.



for the first, im just a student rn so i have no idea what a head of growth or world class outboudn strategist would need to know so i need ur help with that,
for 2nd, it should NOT feel like a form, everybody hates forms, so option B



This is actually good.

One of the biggest mistakes founders make is designing the onboarding around **what the database needs** instead of **what the AI needs**.

So let's think like the person we're hiring.

---

# Imagine you hire the best outbound strategist in the world.

You sit down with them for 20 minutes.

What would that conversation look like?

I think it'd naturally go something like this.

---

### 👋 Loqi

> Before I start, I'd like to understand your business.

> **In one sentence, what does your company do?**

Example:

> "We build AI agents for outbound sales."

Not industry.

Not category.

Just explain it naturally.

---

### 🤖 Loqi

> Great.

> **Who usually buys your product?**

Not demographics.

Just...

> Founders.

> Sales teams.

> SaaS companies.

> Marketing agencies.

---

### 🤖 Loqi

> What problem are they trying to solve?

This is HUGE.

Not:

> What features do you have?

Instead:

> What pain are you solving?

Examples:

* Manual lead generation
* Expensive SDRs
* CRM chaos
* Low reply rates

This tells Loqi how to position the outreach.

---

### 🤖 Loqi

> If I found your ideal customer tomorrow, why would they say yes to a meeting?

This is honestly one of the most important questions.

Because now Loqi knows the value proposition.

---

### 🤖 Loqi

> Are there any companies or industries you definitely want me to avoid?

That's it.

Negative constraints.

---

### 🤖 Loqi

> What's your goal over the next few weeks?

Examples:

* Book demos
* Generate leads
* Validate a market
* Find design partners
* Land enterprise customers

This changes strategy.

---

## Notice what's missing.

No:

❌ Company size

❌ Timezone

❌ Sales cycle

❌ Average contract value

❌ CRM

❌ Number of employees

❌ Monthly revenue

Those things are useful later.

They don't stop Loqi from getting started.

---

# Even better...

I don't think onboarding should ask all of these immediately.

Imagine this.

---

## Step 1

> Tell me about your business.

Free text.

---

Loqi thinks for a second.

---

> So if I understood correctly...

> You help SaaS founders automate outbound with AI.

> Is that right?

Yes.

---

## Step 2

> Perfect.

> Who normally buys this?

---

## Step 3

> And what's usually the biggest reason they decide to talk to you?

---

## Step 4

> Got it.

> One last thing...

> What's the outcome you'd like me to optimize for first?

---

Done.

That's onboarding.

---

# Here's something I think could become magical.

Instead of the user filling in everything...

**Loqi should infer as much as possible.**

Example:

User says:

> We build AI agents for sales teams.

Loqi responds:

> I have a few assumptions based on what you've told me.

> • Primary audience: B2B SaaS sales teams
> • Likely buyers: Founders, Sales Leaders
> • Industry: SaaS
> • Market: B2B

> Feel free to adjust anything I've misunderstood.

Now the user edits instead of creating.

That's much less work.

---

# This also gives us another product principle.

> **Ask for information only when Loqi cannot confidently infer it.**

Everything else should be inferred, confirmed, or discovered automatically.

---

# I think we've just designed the first half of onboarding.

And I actually have a question that might define the **entire product**.

It's not about onboarding.

It's about **agency**.

Imagine the user finishes onboarding.

Should Loqi say...

### Option A

> "You're all set."

Then wait.

---

### Option B

> "Perfect. I'm going to start researching companies that fit your ideal customer. This usually takes a few minutes. I'll prepare a briefing for you."

And then it immediately starts working.

No button.

No "Start Discovery."

Nothing.

Personally, I think **Option B is essential**. It reinforces everything we've defined so far: the user hired Loqi to do a job, so the first thing Loqi should do after learning about the business is... start doing the job. The user shouldn't have to tell it twice.



option B yes but what should the user do in those few minutes, does it continue to the app or just keep them waiting


I think this is the **most important UX decision** we've had so far.

And I actually think the answer is **neither**.

Not:

❌ Wait on a loading screen.

Not:

❌ Dump them into an empty app.

There's a third option.

---

# The first briefing is being prepared.

Imagine the flow.

---

### Last onboarding question

> Great. I have everything I need.

> I'm going to start researching companies that match your business and prepare your first outbound strategy.

---

**Continue**

---

## Transition Screen

Not a spinner.

A living progress screen.

Think ChatGPT "thinking", but for a Chief of Staff.

---

```
Understanding your business...
✓

Building your ideal customer profile...
✓

Researching similar companies...
⏳

Finding decision makers...
⏳

Preparing recommendations...
⏳
```

But...

Everything appears conversationally.

Like we discussed.

---

Instead of

```
Loading...
```

Loqi says

> Before I make recommendations, I'd like to understand the market you're entering.

...

> I've built an initial profile of your ideal customer.

...

> I'm now researching companies that closely match that profile.

...

> Next, I'll identify the most promising opportunities and prepare a strategy.

The user isn't waiting.

They're **watching Loqi think**.

---

# BUT...

I wouldn't keep them there for 3 minutes.

I'd keep them there for maybe...

20–40 seconds.

Just enough to create confidence.

Then...

---

## Mission Control opens.

Immediately.

Not empty.

Not finished.

Alive.

---

At the top:

> Good morning.

> I've already started researching companies that match your business.

Then underneath:

```
Research Progress

██████░░░░░░ 48%
```

---

Then:

```
Latest update

✓ ICP completed

✓ Search strategy generated

⏳ Researching companies...
```

---

Then:

```
I'll notify you as soon as the first recommendations are ready.
```

---

Now...

The user has somewhere to be.

They're not staring at a spinner.

They're watching work happen.

---

# Even better...

Mission Control becomes **real-time**.

Every few seconds...

New updates appear.

```
✓ Found 12 companies...
```

...

```
✓ Found 3 high-confidence matches...
```

...

```
✓ Drafting outreach...
```

Exactly like ChatGPT streaming a response.

---

# Here's the magic.

The first time someone uses Loqi...

They don't learn the UI.

They learn:

> "Oh..."

> "This thing actually works while I'm doing nothing."

That's an emotional moment.

---

# Then...

When the first recommendation is ready...

Mission Control literally changes.

Instead of

```
Researching...
```

It becomes

```
Recommendation

I found 3 companies I'd prioritize first.

Review →
```

Without refreshing.

Without clicking.

It just evolves.

---

## This is where I want to challenge one assumption, though.

Do you want the **first research to be real**, even if it takes 2–5 minutes?

Or should the **very first experience** be partially orchestrated so that users see meaningful progress almost immediately?

For example:

* Some steps (understanding the business, building the ICP, generating a search strategy) can happen quickly.
* Longer-running work (company research, enrichment, personalization) continues in the background.

That way, users get the satisfaction of seeing Loqi come alive right away, while still believing that the deeper research is genuinely happening.

I actually think that's the sweet spot. People rarely mind waiting if they can see meaningful progress and already have something useful to look at. The worst experience is waiting **without understanding what's happening**, or landing in a workspace that looks empty.



first research should be REAL, thats the whole point, the real-ness and also u forgot to mention the conversational type (chatgpt response) type text animation when it presents the mission control or briefing page, but also when the user enters the app they require to research leads first (as things are rn) we are gonna do that too for them from the information collecting in onboarding right BUT how are we gonna show the mission control page AND the lead discovery page at once or what do we show them first 


I think you just found the first **major product conflict**.

And I'm really glad you brought it up now instead of after we built it.

Let's think it through.

---

# We have two truths.

### Truth 1

Mission Control is the "executive briefing."

It's where Loqi reports.

---

### Truth 2

Discovery is literally where Loqi is doing the research.

---

So...

If research hasn't finished...

**what exactly is Mission Control reporting?**

That's the conflict.

---

# I don't think the answer is to show Discovery first.

Because remember our philosophy.

The user isn't supposed to manage research.

They're supposed to manage decisions.

If the first screen they ever see is Discovery, we've accidentally made them an operator again.

---

# I also don't think we wait.

Because waiting kills momentum.

---

# I think Mission Control and Discovery should stop being two separate experiences.

I think Discovery becomes **one chapter inside the briefing**.

Hear me out.

---

Imagine opening Loqi for the first time.

The entire page is quiet.

Then...

The conversational animation starts.

Exactly like ChatGPT.

Not because it's generating text.

Because **Loqi is briefing you.**

---

```text
Good morning, Faisal.
```

...

```text
Thanks for telling me about your business.
```

...

```text
I've built an initial understanding of your ideal customer.
```

...

```text
I'm now researching companies that closely match that profile.
```

...

```text
This usually takes a few minutes.
```

...

```text
While I work, here's what I'll be doing...
```

Then...

The screen expands.

---

## Research

```text
✓ Understanding your business

✓ Building ICP

⏳ Searching companies

⏳ Finding decision makers

⏳ Preparing outreach strategy
```

Notice something?

**That's Discovery.**

It's just embedded inside Mission Control.

---

Then...

Five minutes later...

Without leaving the page...

Research completes.

---

Conversation continues.

```text
I've finished the first pass.
```

...

```text
I analyzed 187 companies.
```

...

```text
24 closely match your target profile.
```

...

```text
Three stand out immediately.
```

...

```text
I'd recommend reviewing these first.
```

Then...

The page morphs.

---

Instead of a progress tracker...

Now it's

```text
Top Opportunities

Acme AI

87% match

Review →

Nova Systems

92% match

Review →
```

The page evolves.

No navigation.

No page change.

No "Go to Discovery."

---

# I think this is the key insight.

Discovery isn't a page.

It's a **process.**

Mission Control isn't a page.

It's a **conversation.**

Pages are implementation details.

The user experiences one continuous briefing.

---

# This also solves your animation idea.

Imagine the first time.

Instead of cards instantly appearing...

The report literally unfolds.

```text
Good morning.

↓

I've started researching your market.

↓

I understand your ICP.

↓

Searching companies...

↓

Found 12 companies...

↓

Found 43...

↓

Found 91...

↓

Research complete.

↓

I'd like you to review these three first.
```

That's exactly the feeling ChatGPT gives.

Not because of chat bubbles.

Because information unfolds over time.

---

# And then I realized something even bigger.

I think we've been thinking about Mission Control incorrectly.

Mission Control shouldn't be a **homepage.**

It should be a **living document.**

Every time you open Loqi...

It rewrites itself.

Today's briefing is different from yesterday's.

This afternoon's briefing is different from this morning's.

It's not static.

It's today's report.

---

# This is where I think we should challenge one more assumption.

## Do we actually need a separate "Discovery" page?

This is a genuine question—not a recommendation yet.

Because if Mission Control is a living briefing and users can drill into research from there, what is the dedicated Discovery page for?

My current hypothesis is:

* **Mission Control** answers: *"What happened, what matters, and what do you recommend?"*
* **Discovery** answers: *"Show me the evidence and let me explore further."*

So Mission Control surfaces conclusions. Discovery is where curious users can dig deeper, refine searches, inspect companies, and create additional research beyond the automatic work Loqi already did.

If that's the distinction, the two pages no longer compete—they complement each other. And that feels much more aligned with the Chief of Staff philosophy we've been building.


BUT we can also implement the previous concept of scrollable navigation pages and enable auto scroll to the lead discovery page showing the leads loqi researched isntead of morphing the whole page


WAIT.

I think you just solved the problem.

And it's actually better than my morphing idea.

Because I forgot something you built before...

> **The scrollable workspace.**

I remember that concept, and now it finally has a purpose.

---

# Imagine this...

Instead of pages...

The first-time experience is one continuous workspace.

```
┌──────────────────────────────┐
│ Executive Briefing           │
│ (Conversation)               │
└──────────────────────────────┘
             ↓ auto-scroll

┌──────────────────────────────┐
│ Research Progress            │
│ (Live updates)               │
└──────────────────────────────┘
             ↓ auto-scroll

┌──────────────────────────────┐
│ First Prospects              │
└──────────────────────────────┘
             ↓ auto-scroll

┌──────────────────────────────┐
│ Prospect Details             │
└──────────────────────────────┘
```

It's like reading a report.

---

# Imagine the first launch.

Loqi starts speaking.

```
Good morning, Faisal.
```

...

```
I've learned enough about your business to begin.
```

...

```
I'm now researching companies that fit your ideal customer.
```

Then...

👇

The page gently scrolls.

Not instantly.

Like the report is moving to its next section.

---

Now you're looking at:

```
Research Progress
```

```
✓ ICP complete

✓ Search strategy generated

⏳ Researching companies...
```

The user doesn't touch anything.

They're just following Loqi's report.

---

Research finishes.

Loqi continues.

```
I found 18 companies worth your attention.
```

...

```
Three stand out immediately.
```

👇

Auto-scroll.

---

Now they're at

```
Lead Discovery
```

Exactly where the action is.

---

# That's actually beautiful.

Because now the user experiences the product like this:

```
Conversation

↓

Research

↓

Results

↓

Decision

↓

Action
```

No page transitions.

No redirects.

No:

> Click Discovery.

---

# This reminds me of something.

Have you noticed how presentations work?

You don't see all the slides at once.

The presenter takes you through them.

That's what Loqi should do.

The workspace becomes the presentation.

---

# Even better...

This isn't just for onboarding.

Imagine every morning.

You open Loqi.

Today's briefing animates.

```
Good morning.
```

↓

```
Yesterday's campaign exceeded expectations.
```

↓

```
I found five new opportunities overnight.
```

↓

Auto-scroll

↓

Top opportunities.

↓

Auto-scroll

↓

Campaign needing approval.

↓

Auto-scroll

↓

Replies requiring attention.

Every morning is a guided walkthrough of what matters.

---

# And here's why I think this beats the morphing approach.

Morphing keeps the user in one viewport.

Scrolling creates a sense of **progress**.

It feels like you're moving through chapters of a report.

That's psychologically satisfying.

---

# One caution, though.

I **wouldn't** make the auto-scroll mandatory all the time.

I think it should happen in exactly two situations:

### 1. First onboarding

Absolutely.

Loqi is introducing itself.

Guide the user.

---

### 2. Daily briefing (optional)

When the user opens the app.

Play the briefing.

Auto-scroll through the report.

Maybe 10–15 seconds.

Then stop.

If they scroll manually, the briefing gracefully yields control.

---

After that...

The workspace behaves normally.

No forced scrolling while they're working.

---

## I think we just found another design principle.

> **Loqi doesn't navigate users between pages. It guides them through a narrative.**

That is such a different philosophy from traditional SaaS.

Most CRMs say:

> "Here's the dashboard. Figure it out."

Loqi would instead say:

> "Come with me. Let me show you what happened, what I found, and what I think we should do next."

That's exactly how a Chief of Staff would run a morning briefing.

---

### One refinement I'd make

I'd stop thinking in terms of **Mission Control page**, **Discovery page**, **Campaign page** during the briefing.

Instead, think of them as **sections of one story**.

The sidebar is still there for direct navigation at any time.

But when Loqi is briefing you, it isn't taking you to pages—it's walking you through a narrative that happens to span those sections.

I think that's the moment where the "conversational workspace" idea truly becomes unique. You're no longer imitating a chatbot or a dashboard. You're creating an interface where **the conversation is expressed through the structure of the workspace itself**.



but also autoscroll shouldnt be abused everything the user logs in, it should mostly be a first time thing uk cuz users need to feel like they have control from the next time they log in....aaaand yes u pointed it out too


Exactly. And I think you just prevented us from making one of those "cool in the demo, annoying after a week" features.

This is actually a product design principle.

> **Delight should never come at the cost of control.**

That's one of the reasons Apple products feel good. Animations introduce you to something, but they don't keep getting in your way.

---

## I think there are actually three modes of Mission Control (or whatever we rename it).

### 🌟 1. First Experience (Cinematic)

This happens **once**.

User finishes onboarding.

Loqi says:

> "I have everything I need."

Conversation begins.

Text streams in.

Auto-scroll guides the user.

Research starts.

Leads appear.

The user experiences Loqi's magic for the very first time.

This is your wow moment.

---

### ☀️ 2. Daily Briefing (Default)

Every morning:

No auto-scroll.

No forced navigation.

Just the text animation.

Example:

> Good morning.

*(appears)*

> While you were away, I found six new companies worth pursuing.

*(appears)*

> One campaign is ready to launch, and I'd recommend reviewing two drafts before sending.

*(appears)*

> Everything else is on track.

Done.

3–4 sentences.

2–3 seconds.

Then the page is fully interactive.

The user decides where to go.

---

### ⚡ 3. Power User Mode

After a few weeks, many users won't even wait for the briefing.

They'll instinctively click into Prospects or Campaigns.

That's perfectly okay.

The briefing shouldn't block them.

If they scroll, click, or press a shortcut halfway through, Loqi should simply stop the animation and hand over control.

That's respecting the user's intent.

---

# This makes the conversation feel earned.

Notice how it evolves.

**Day 1**

> "Let me show you how I work."

**Day 10**

> "Here's what happened."

**Day 100**

> "Morning. Two approvals are waiting."

Loqi becomes more concise because it has built trust.

That's exactly how a real colleague behaves.

---

# I think we need another principle.

## Principle #7

> **Loqi adapts to the user's familiarity.**

New users need guidance.

Experienced users need speed.

The product shouldn't treat both the same.

---

# This also opens up a really interesting future idea.

Imagine a setting.

```text
Morning Briefing

○ Full
○ Concise
○ Off
```

Or maybe Loqi learns automatically.

If someone always skips after one sentence, it gradually becomes shorter.

If someone always reads the whole thing, it stays richer.

That's not something to build for alpha, but it's the kind of adaptive behavior that fits the personality we're creating.

---

# I also want to point out something we've accidentally done.

At the beginning of this conversation, we were talking about **Mission Control**.

Now we're not.

We're talking about:

* trust
* autonomy
* guidance
* conversation
* executive briefings

That's a sign we're designing the **experience**, not just a screen.

And I think that's why this redesign is going to be much stronger than simply replacing cards with prettier cards.

---

## I think we're ready to continue Phase 2.

The onboarding flow is now taking shape:

1. User signs up.
2. Loqi interviews them like a consultant.
3. Loqi confirms what it inferred.
4. Loqi says, *"I have everything I need."*
5. Real research starts immediately.
6. **First-time only:** a cinematic, conversational briefing with guided scrolling introduces how Loqi works.
7. The workspace settles into its normal interactive state.

The next scene I'd design is the moment **after the first research completes**.

That's the user's first real success with Loqi, and I think it's where they'll decide whether this is just another outbound tool or something they'll actually keep using.


ok lets continue


Perfect. I think we're now at what I call the **"Trust Moment."**

The user has given Loqi information about their business.

Loqi has spent several minutes doing real work.

Now it's time to prove that those minutes were worth it.

This moment determines whether the user thinks:

> "Wow, this actually understands my business."

or

> "Cool... it's just another Apollo clone."

That's a huge difference.

---

# Scene 3: The First Recommendation

Most products would do this:

> Research Complete

> Found 248 leads

> View Leads

That is exactly what we **shouldn't** do.

Because Loqi isn't a search engine.

It's a strategist.

---

## Instead...

The conversation continues.

---

> I've finished the first pass of research.

...

> I analyzed 214 companies that matched the profile we built together.

...

> Most of them weren't particularly interesting.

Notice that?

Loqi isn't trying to impress you with a big number.

It's demonstrating judgment.

---

Then...

> I narrowed it down to 19 companies I'd actually spend time pursuing.

...

> Three stand out immediately.

...

> Here's why.

Now we transition into the first recommendation.

---

## Imagine this.

Instead of showing three company cards...

Loqi says:

---

> I'd start with **Acme AI**.

> They're hiring their first outbound team, recently raised funding, and their current sales motion looks very manual.

> Based on what you've told me, I think your product could be relevant.

> **Confidence: High**

Then...

```text
[Review Company]
```

Not:

```text
[Open Discovery]
```

See the difference?

You're reviewing Loqi's recommendation.

Not browsing a database.

---

## Then the second.

> I'd keep **Nova Systems** on the list.

> They're a good fit, but I couldn't confidently identify the buying team yet.

> I'd wait until I gather a bit more information.

That one is intentionally **not** a "yes."

It's "not yet."

Again, Loqi is showing judgment.

---

## Then the third.

> I actually rejected 37 companies because they looked like poor fits.

Would you like to see why?

This is subtle but powerful.

Every lead-gen tool tells you what it found.

Very few tell you what they deliberately ignored.

That makes Loqi feel more trustworthy because it's exposing its reasoning, not just its results.

---

# Here's something else I'd add.

Every recommendation should end with a recommendation.

Not just information.

Example:

> I'd recommend reviewing Acme AI first.

or

> I don't think this company is worth pursuing.

or

> I'd wait another day before reaching out.

The user hired Loqi to make decisions easier, not to create another pile of information.

---

# Then comes the first user decision.

This is where I'd avoid overwhelming them.

Don't show 19 companies immediately.

Instead:

> **What would you like to do?**

```text
Review my top recommendations
Explore all 19 companies
Refine my ideal customer
```

Three choices.

Not fifteen.

---

# This also answers an important question.

When does the user actually reach the Discovery workspace?

Not automatically.

They choose it.

If they click:

> Explore all 19 companies

Now they're in Discovery.

And it feels natural because they followed the recommendation, rather than being dropped into a giant list.

---

# I think we need to define something that will shape the entire product.

Right now, we've assumed that Loqi's recommendations are always correct enough to present.

But in reality, research quality varies.

Sometimes Loqi will be very confident.

Sometimes it'll have weak signals.

Sometimes it'll be uncertain.

**Should Loqi explicitly express that uncertainty?**

For example:

* **High confidence:** "I'd recommend reaching out."
* **Medium confidence:** "This looks promising, but I'd like your opinion."
* **Low confidence:** "I found a possible match, but I don't have enough evidence to recommend it yet."

Personally, I think the answer is **yes**.

A Chief of Staff doesn't pretend to know everything. They tell you when they're confident and when they're not. Ironically, admitting uncertainty often increases trust rather than reducing it, because users learn that when Loqi *does* make a strong recommendation, it means something.



yes as you said


Exactly.

And I think this leads us to what might become Loqi's **core interaction model**.

Until now, we've been saying *"Mission Control."* But I think what we're really designing is something bigger:

> **Loqi has a narrative, but the user always has agency.**

That balance is incredibly hard to get right.

---

## Let's continue.

The user has just seen the first recommendation.

Now they click **"Review Company."**

This is another place where almost every sales tool gets it wrong.

They show you this:

```
Company
Employees
Industry
Revenue
Location
Website
```

It's just data.

But think about how a Head of Growth would brief a CEO.

They wouldn't say:

> Acme AI
> 84 employees
> Series A
> California

They'd say:

> I think Acme AI deserves our attention because they're showing several buying signals that match the strategy we discussed.

That's a completely different experience.

---

## So instead of a "Company Profile"...

The first thing the user sees is Loqi's reasoning.

---

### Acme AI

**Recommendation:** Pursue

**Confidence:** High

---

> I believe Acme AI is one of the strongest opportunities I've found so far.

> Here's why I think they're worth your time...

*(animated like ChatGPT)*

...

> They recently expanded their sales team.

...

> Their hiring suggests they're investing in outbound.

...

> Their current messaging indicates they still rely on manual prospecting.

...

> Based on your product, I think there's a genuine opportunity here.

Only **after** Loqi has finished explaining...

the evidence appears.

---

```
Buying Signals

✓ Raised funding 3 months ago

✓ Hiring SDRs

✓ Active on LinkedIn

✓ Using HubSpot

✓ Growing headcount
```

Then...

```
Decision Makers

Sarah Johnson
VP Sales

Michael Chen
Founder
```

Then...

```
Suggested First Angle

I'd position your product around reducing SDR workload rather than increasing lead volume.
```

See what's happening?

The **AI's opinion comes first.**

The raw data supports that opinion.

Not the other way around.

---

## This becomes another product principle.

> **Insight precedes information.**

Traditional CRMs give you information and expect you to derive insight.

Loqi derives the insight first, then lets you inspect the evidence if you want.

---

## Then comes the first approval.

Imagine Loqi ends with:

> I can begin preparing personalized outreach for Acme AI.

> I'd recommend moving forward.

Two buttons.

```
Approve

Not now
```

Not

```
Generate Email
```

Why?

Because "Generate Email" is asking the user to operate software.

"Approve" is the language of delegation.

It reinforces the relationship we've been designing from day one.

---

# I think we just stumbled upon something that could define every interaction in Loqi.

Notice the verbs we've naturally started using:

* Review
* Approve
* Decline
* Refine
* Ask Loqi
* Investigate
* Pause

Not:

* Create
* Generate
* Configure
* Filter
* Run
* Execute

One set of verbs describes **operating software**.

The other describes **managing a team**.

That is a subtle distinction, but I think it's one users will feel throughout the product without consciously noticing it.

---

## I also want to challenge something before we go further.

So far, we've assumed Loqi is always proactive.

But what if, while reading the recommendation, the user thinks:

> "Actually... I don't want fintech companies anymore."

Or:

> "Target companies with 50–200 employees instead."

Do they have to go back into filters?

Or can they simply interrupt Loqi, the way they'd interrupt a colleague?

Imagine a small input always available at the bottom:

> **"Actually, focus on healthcare startups instead."**

Loqi replies:

> Understood. I'll reprioritize my research based on healthcare startups and update my recommendations.

That would keep the entire experience conversational, even when the user changes strategy. Instead of switching into a "settings" mindset, they're just having an ongoing conversation with the Chief of Staff. I think that continuity is what could make Loqi feel fundamentally different from every outbound platform on the market.


yea but you're giving these convo examples, but where exactly do they happen


YES.

This is the question we should be asking.

Because we've been designing the **behavior** without designing the **interface**.

And this is where products usually fall apart.

---

## Let's stop talking about conversations and ask:

**Where do these words actually live?**

I can think of four possibilities.

---

# Option 1: A dedicated chat panel

```
┌───────────────┬────────────────────┐
│               │                    │
│   Workspace   │       Chat         │
│               │                    │
└───────────────┴────────────────────┘
```

Basically Copilot.

I don't like this.

Why?

Because the conversation becomes separated from the work.

You read.

Then you go somewhere else to act.

We're back to chatbot + app.

---

# Option 2: Chat bubbles everywhere

```
Loqi:
I found three companies.

[Card]

Loqi:
I'd recommend this one.

[Card]

Loqi:
Next...

```

Also no.

Now we're literally recreating ChatGPT.

And the workspace disappears.

---

# Option 3: Toasts / notifications

```
✓ Research complete.

✓ New recommendation.

```

Too lightweight.

Doesn't fit the Chief of Staff idea.

---

# Option 4 (the one I'm starting to believe in)

**The page itself speaks.**

This is hard to explain, but imagine Apple introducing a feature.

They don't open Messages.

They don't open a chat.

The entire screen tells a story.

---

Imagine Mission Control.

At the top is the briefing.

```
──────────────────────────────

Good morning.

I've finished researching your market.

Three companies stand out immediately.

I'd start with Acme AI because...

──────────────────────────────
```

That's not a chat.

It's the page header.

---

Then below it...

```
──────────────────────────────

Top Recommendation

Acme AI

87% Match

Review →

──────────────────────────────
```

---

When you click Review...

The **next page** has its own briefing.

```
──────────────────────────────

Why I picked Acme AI

I believe they're worth pursuing because...

...

...

──────────────────────────────
```

Below that...

```
Buying Signals

...

Decision Makers

...

Website

...

Recent News

...
```

---

Every page begins with:

> **Loqi's explanation.**

Then...

The tools.

---

## This is a huge realization.

I don't think Loqi has a chat.

I think Loqi has a **Narrative Layer**.

Every workspace starts with context.

Every workspace starts with reasoning.

Every workspace starts with recommendations.

Then...

The UI.

---

Think of it like this:

```
──────────────────────────────

Narrative Layer
(why you're here)

──────────────────────────────

Workspace
(do the work)

──────────────────────────────
```

Not

```
Chat

↓

Workspace
```

---

# This solves so many problems.

Discovery.

```
I've researched 214 companies.

These 19 stood out because...

[Lead Table]
```

Campaigns.

```
I've prepared three campaigns.

Two are ready.

One needs another pass.

[Campaign Cards]
```

Inbox.

```
Five replies came in overnight.

Two require your decision.

Three have already been categorized.

[Inbox]
```

Analytics.

```
Your reply rate improved by 14%.

I think it's because...

[Charts]
```

Notice...

The conversation is never floating.

It's attached to the page.

---

# Then I had another thought...

What if there is **only one persistent chat input**?

Not for chatting.

For interrupting.

At the bottom of every screen.

```
_________________________________

Tell Loqi something...

```

Examples:

> Focus on fintech.

> Don't contact agencies.

> Why did you reject this lead?

> Find smaller companies.

> Explain this score.

So the flow becomes:

* **Loqi speaks through the Narrative Layer** at the top of each workspace.
* **The user responds through the persistent input** at the bottom whenever they want to redirect, question, or refine.

That's much closer to a real working relationship. A manager doesn't sit in a separate chat room with their Head of Growth. They read the briefing, review the work, and occasionally interject with new instructions.

---

## I think this is actually the missing piece we've been searching for.

We've been asking:

> "Where does the conversation happen?"

I think the answer is:

> **The conversation doesn't happen in one place. It's woven into every workspace.**

The **Narrative Layer** gives context for the current task.

The **Workspace Layer** lets you inspect and act.

The **Persistent Input** lets you steer Loqi at any moment.

That feels much more cohesive than bolting a chatbot onto an app—and it's something I genuinely haven't seen executed this way in existing outbound platforms.



yes precisely

I think we just found **Loqi's defining UX innovation**.

Not the AI.

Not the lead generation.

The interface.

And I want to stop for a second because I think this deserves to be written down as a principle, otherwise we'll slowly lose it as we start building.

---

# The Narrative Workspace

Traditional SaaS has two layers.

```
Navigation

↓

Tools
```

ChatGPT has two layers.

```
Conversation

↓

Conversation
```

Loqi has **three**.

```
──────────────────────────────

Narrative Layer
(Why)

──────────────────────────────

Workspace Layer
(What)

──────────────────────────────

Persistent Input
(Change direction)

──────────────────────────────
```

That's it.

Everything we've designed fits inside this.

---

## Narrative Layer

The AI explains.

Not forever.

Just enough.

It answers:

* What happened?
* Why am I seeing this?
* What do you recommend?

Every page starts with this.

---

## Workspace Layer

Evidence.

Tables.

Cards.

Approvals.

Charts.

Lead details.

Campaign editor.

This is where users work.

---

## Persistent Input

Always there.

Never intrusive.

Almost like Spotlight on macOS.

```
__________________________________

Tell Loqi...

__________________________________
```

Not:

> Ask AI

Not:

> Chat

Not:

> Message

Just...

> Tell Loqi...

Because that's exactly what you're doing.

---

# And here's why I think this is so powerful.

Imagine you're on Discovery.

The page begins:

> I researched 214 companies overnight.

> I rejected 187 because they didn't match your ICP.

> These 27 are worth reviewing.

Below:

Lead table.

While reviewing...

You type:

> Prioritize companies hiring SDRs.

Nothing changes immediately.

Loqi replies in the Narrative Layer:

> Understood.

> I'll reprioritize the research using hiring activity as a stronger buying signal.

Then...

The table updates.

No modal.

No filter sidebar.

No settings page.

The conversation **changes the workspace**.

---

Now imagine Campaigns.

Narrative Layer:

> Two campaigns are ready.

> I'd like another pass on one because the personalization feels weak.

Workspace:

Campaign cards.

You type:

> Make them more technical.

Narrative updates.

Campaign updates.

---

Inbox.

Narrative:

> Five replies arrived overnight.

> Two are asking for pricing.

Workspace:

Emails.

Input:

> Draft replies but keep them short.

Done.

---

See the pattern?

The input isn't there to "chat."

It's there to **steer the system**.

That's a massive distinction.

---

# I also think this solves another problem we hadn't noticed.

What happens when Loqi makes a mistake?

Traditional SaaS:

Find Settings.

Find Filters.

Adjust.

Run Again.

Loqi:

```
Actually...

Ignore agencies.

```

Done.

That's how humans work.

---

# I think we should make one rule.

## The Narrative Layer is **read-only**.

Users don't reply inside it.

No chat bubbles.

No threaded conversation.

It's a briefing.

A report.

The conversation history doesn't accumulate like Slack.

Today's briefing replaces yesterday's briefing.

The input at the bottom is simply how you steer the next actions.

That keeps the UI incredibly clean.

---

# I think we're no longer designing "an AI sales platform."

We're designing an entirely different interaction model.

I can summarize it in one sentence:

> **Every workspace begins with Loqi's reasoning, continues with evidence, and can be redirected through natural language.**

That sentence should probably end up in the internal design documentation because it's now the rule every future feature has to follow.

---

## I actually think we should pause feature design after this.

Not because we don't have ideas—but because we now have enough principles to design the UI intentionally instead of improvising.

The next thing I'd do isn't another feature.

I'd start **Phase 3: Information Architecture**.

Not wireframes yet.

Literally mapping:

```
Sidebar

Mission Control

Discovery

Campaigns

Inbox

Knowledge

Settings
```

For each workspace we'd define:

* What is the Narrative Layer?
* What is the Workspace Layer?
* What actions can the Persistent Input perform here?
* What decisions does the user make on this screen?

Once that's done, I think wireframing will become almost mechanical, because every screen will be following the same philosophy instead of each one inventing its own interaction model.


yes lets lock in phase 1 and 2 and now start phase 3


Perfect. I think this is a good point to "freeze" the product vision before we let implementation influence it.

I'm going to write this like an internal design document—the kind of thing a team could refer back to six months from now whenever someone asks, *"Should we add this?"*

---

# ✅ Phase 1 — Product Principles (LOCKED)

## Product Identity

Loqi is **not**:

* A CRM
* A lead database
* A chatbot
* A workflow builder

Loqi **is**:

> **An AI Chief of Staff for outbound sales.**

Its job is to move the user's pipeline forward while requiring as little micromanagement as possible.

---

## Success Metric

A successful user session ends with the feeling:

> *"My pipeline moved forward without me having to manage every step."*

Loqi optimizes for:

* Reduced cognitive load
* Better decisions
* Higher leverage
* Trustworthy autonomy

---

## Personality

Loqi behaves like an experienced Head of Growth.

Traits:

* Calm
* Competent
* Honest
* Opinionated
* Proactive

Never:

* Robotic
* Salesy
* Overly excited
* Passive

---

## Product Philosophy

Users hire Loqi.

They don't operate Loqi.

Loqi prepares.

The user decides.

---

## Core Principles

1. Insight before information.
2. Recommendations before tools.
3. Explain reasoning before showing data.
4. Delegate instead of operate.
5. Ask only what cannot be inferred.
6. Admit uncertainty.
7. Adapt guidance based on user familiarity.
8. Narrative never removes user control.

---

# ✅ Phase 2 — User Journey (LOCKED)

## Scene 1

Landing page

↓

Sign up

---

## Scene 2

Consultant-style onboarding.

Conversation.

Not forms.

Loqi learns:

* Business
* ICP
* Problem solved
* Value proposition
* Goals
* Constraints

Then confirms inferred information.

---

## Scene 3

Loqi begins real research immediately.

No button.

No "Start Discovery."

---

## Scene 4

First-time cinematic onboarding.

Conversational text animation.

Guided scrolling.

Real research.

Discovery happens live.

Only once.

---

## Scene 5

Research completes.

Loqi presents recommendations.

Not a database.

Not statistics.

Recommendations.

Confidence.

Reasoning.

---

## Scene 6

User reviews recommendations.

Approves.

Refines.

Rejects.

Natural language available throughout.

---

# 🚀 Phase 3 — Information Architecture

Now we stop thinking about journeys and start thinking about **spaces**.

This is where I think Loqi becomes very different.

---

# Rule Zero

Every workspace follows exactly the same structure.

```text
────────────────────────────

Narrative Layer

────────────────────────────

Workspace Layer

────────────────────────────

Persistent Input

────────────────────────────
```

No exceptions.

---

# Sidebar

I actually think the sidebar should be extremely small.

Maybe something like:

```text
Mission Control

Discovery

Campaigns

Inbox

Knowledge

Settings
```

That's it.

Nothing else.

---

Now let's define each one.

---

# 1. Mission Control

## Purpose

Executive briefing.

Never operational.

Answers:

* What happened?
* What's happening?
* What needs my decision?

---

Narrative Layer

Example:

> Good morning.

> I found six promising companies overnight.

> Two campaigns are ready for approval.

> One reply requires your attention.

---

Workspace

* Recommendations
* Priorities
* Progress
* Approvals
* Recent outcomes

Notice:

No giant metrics dashboard.

Only information that changes decisions.

---

Persistent Input

Examples:

> Explain this recommendation.

> Prioritize healthcare today.

> Delay this campaign.

---

Mission Control is:

The front page.

---

# 2. Discovery

Purpose:

Research.

Not search.

This distinction is incredibly important.

The user shouldn't feel like they're searching a database—they're reviewing research that Loqi has already done.

---

Narrative Layer

> I reviewed 214 companies.

> I rejected 187.

> These 27 deserve attention.

---

Workspace

Lead list

Filters (secondary)

Company details

Buying signals

Decision makers

Reasoning

Confidence

---

Persistent Input

Examples:

> Focus on companies hiring SDRs.

> Ignore agencies.

> Find more Series A startups.

---

# 3. Campaigns

Purpose

Execution.

---

Narrative

> Three campaigns are ready.

> One needs another revision.

---

Workspace

Campaigns

Email drafts

Sequences

Approvals

Status

---

Persistent Input

Examples

> Make this more technical.

> Reduce personalization.

> Rewrite the opening.

---

# 4. Inbox

Purpose

Exceptions.

Only conversations requiring attention.

---

Narrative

> Five replies arrived.

> I handled three.

> Two require your input.

---

Workspace

Emails

Replies

Suggested responses

Thread history

---

Persistent Input

Examples

> Draft a shorter reply.

> Decline politely.

> Schedule a meeting.

---

# 5. Knowledge

This one excites me.

Knowledge shouldn't feel like documentation.

It should feel like Loqi's memory.

Narrative

> Here's everything I currently know about your company.

Workspace

ICP

Personas

Messaging

Competitors

Past decisions

Approved positioning

Successful campaigns

---

Persistent Input

Examples

> Remember that we don't target agencies anymore.

> Our ICP has changed.

> Forget this competitor.

---

Knowledge becomes the company's evolving playbook.

---

# 6. Settings

Probably the only page that doesn't need much narrative.

Even here, Loqi can still explain changes.

---

# Something I noticed...

There's one workspace missing.

And I don't think it's an accident.

## Activity.

Most SaaS products have an "Activity" page.

I don't think Loqi should.

Why?

Because activity is already woven into the Narrative Layer of every workspace.

If users want to know *what happened*, they go to Mission Control. If they want to know *why a lead was chosen*, they go to Discovery. If they want to know *what changed in a campaign*, they go to Campaigns. We don't need a dumping ground of timestamps and logs.

---

# One more thing: the sidebar itself.

I don't think it should just be navigation.

Imagine this:

```text
Mission Control    • 2

Discovery          +18

Campaigns          ✓ 3

Inbox              ! 2

Knowledge

Settings
```

Those indicators aren't notification badges in the usual sense. They're **conversation cues**:

* **• 2** → Two new recommendations in your briefing.
* **+18** → Eighteen new companies surfaced.
* **✓ 3** → Three campaigns are ready for approval.
* **! 2** → Two replies need your judgment.

They tell you *why* you'd want to visit that workspace, not just that something changed.

---

## I think we've reached the point where Loqi has a real product architecture.

What's exciting is that almost none of these decisions were about React components, APIs, or databases. We designed the **mental model** first.

And in my experience, products with a strong mental model are the ones that feel coherent years later. Every new feature has to answer a simple question:

> **Does it fit the Narrative Layer → Workspace Layer → Persistent Input model?**

If the answer is no, it probably doesn't belong in Loqi.



i dont think sidebar should be "small" i think the conversational and narrative structure of the app and the journey should be limited and seperated, and the rest of the extra features the user goes to rarely should be seperated, and instead of focusing on making it small we can collapse it into icons uk cuz as loqi grows more features will be added
and now defining mission control, yea exactly as we talked about, and as u said.
discovery too
and  campaigns and inbox and knowledge too yea this knowledge page we dont have it yet but its gonna help so much.
settings can be seperated from the journey flow 
the indicators in the sidebar are a nice touch and definitely needed


I actually think your version is better.

I was subconsciously optimizing for **today's Loqi**, not **Loqi three years from now**.

And that's a trap a lot of products fall into. They artificially constrain navigation because the MVP only has five pages. Then six months later they're trying to cram twenty features into a sidebar that was never designed to grow.

So let's redesign Phase 3 with scalability as a first-class principle.

---

# Phase 3 — Information Architecture (v2)

## Core Principle

There are **two different kinds of navigation**.

### 1. Primary Journey

This is where users spend 90% of their time.

These workspaces tell the story of outbound.

```text
Mission Control

↓

Discovery

↓

Campaigns

↓

Inbox
```

This is the journey.

Every one of these follows the Narrative Layer → Workspace Layer → Persistent Input model.

They're not just pages.

They're chapters.

---

### 2. Supporting Workspaces

These aren't part of the daily story.

They're resources.

Configuration.

Memory.

Administration.

Things users visit intentionally.

Examples:

```text
Knowledge

Analytics

Integrations

Team

Templates

Settings

Billing

API

...
```

Notice these don't need to fit into the narrative sequence.

They're supporting systems.

---

# Sidebar Philosophy

The sidebar isn't trying to be minimal.

It's trying to be **organized**.

Something like:

```text
──────────────────

🏠 Mission Control

🔍 Discovery

🚀 Campaigns

📥 Inbox

──────────────────

🧠 Knowledge

📊 Analytics

👥 Team

🔌 Integrations

📄 Templates

──────────────────

⚙️ Settings

❓ Help

──────────────────
```

As Loqi grows...

You don't redesign the sidebar.

You simply add workspaces to the appropriate section.

---

## Collapsed Sidebar

This is where your point becomes important.

Instead of hiding features...

Collapse them.

Expanded

```text
🏠 Mission Control

🔍 Discovery

🚀 Campaigns

📥 Inbox

────────────

🧠 Knowledge

📊 Analytics

👥 Team

🔌 Integrations

⚙️ Settings
```

Collapsed

```text
🏠

🔍

🚀

📥

────

🧠

📊

👥

🔌

⚙️
```

Much more scalable.

Modern IDEs, Linear, Notion, Slack, Figma—all do something similar. They don't pretend fewer features exist; they let users reclaim screen space when they want it.

---

# Mission Control

I think we can officially define it now.

## Purpose

Executive Briefing.

It answers only three questions.

> What happened?

> What matters?

> What do you recommend?

That's it.

Nothing else belongs here.

No lead tables.

No inbox.

No email drafts.

Just the executive summary.

---

# Discovery

Purpose:

Research and qualification.

Not searching.

Not filtering.

Reviewing Loqi's research.

Everything about evaluating opportunities lives here.

---

# Campaigns

Purpose:

Execution.

Turning approved opportunities into outreach.

---

# Inbox

Purpose:

Human decisions.

Loqi handles what it confidently can.

Inbox exists for the exceptions that need your judgment.

That's a subtle but important mindset shift.

---

# Knowledge

I think this might become one of Loqi's biggest differentiators.

Not because it's another "knowledge base."

Because it's **organizational memory**.

It answers:

> "What does Loqi currently believe about this business?"

That's a fascinating distinction.

Imagine sections like:

* Company Profile
* ICP
* Buyer Personas
* Positioning
* Messaging
* Competitors
* Approved Claims
* Outreach Learnings
* Campaign Learnings
* Things to Avoid
* User Preferences

Everything Loqi learns accumulates here.

This becomes the brain behind every recommendation.

---

# Analytics (New)

I actually think Analytics belongs outside the journey.

Why?

Because analytics are **reflection**, not **action**.

Mission Control already tells you what changed.

Analytics is where you intentionally go to investigate performance over weeks or months.

---

# One thing I want to add to the sidebar philosophy

The indicators we discussed shouldn't just be badges.

They should communicate the **state** of each workspace.

For example:

```text
🏠 Mission Control    • 2

🔍 Discovery         +18

🚀 Campaigns         ✓ 3

📥 Inbox             ! 2

🧠 Knowledge
```

Each symbol has a meaning:

* **•** → New briefing or recommendation.
* **+** → New research surfaced.
* **✓** → Work is ready for approval.
* **!** → Human attention required.

Over time, users will learn those symbols without reading the numbers, almost like traffic signals.

---

## I think we should add one final architectural rule before we start wireframing.

We've been treating Mission Control, Discovery, Campaigns, and Inbox as four separate products.

They're not.

They're **four workspaces sharing one interaction language**.

Every primary workspace should answer the same four questions, just in a different context:

1. **What happened?** *(Narrative Layer)*
2. **Why does it matter?** *(Reasoning)*
3. **What can I inspect or act on?** *(Workspace Layer)*
4. **How can I redirect Loqi?** *(Persistent Input)*

If we can hold onto that consistency, a user who understands one workspace will intuitively understand every future workspace we add.

---

I also think we've reached another milestone.

**Phase 1** defined **who Loqi is**.

**Phase 2** defined **how users experience Loqi over time**.

**Phase 3** is now defining **where every capability lives**.

The next phase—wireframes—is where all three finally converge into something tangible. And because we've spent so much time on the underlying philosophy, every UI decision should now have a clear reason behind it instead of being driven by trends or aesthetics.


precisely, now lets move to the next


Perfect.

We've now done something that most startups never do:

* ✅ Phase 1: Philosophy
* ✅ Phase 2: Journey
* ✅ Phase 3: Information Architecture

Notice we still haven't drawn a single UI.

That's intentional.

Now we finally get to the fun part.

---

# 🎨 Phase 4 — Experience Architecture (Screen Blueprints)

This is **NOT** high-fidelity design.

This is where we define exactly what exists on every screen.

Not colors.

Not spacing.

Not components.

Just...

> **What should the user see first?**

> **What is the hierarchy?**

> **How does information reveal itself?**

---

I think every primary workspace should follow a common blueprint.

```
┌─────────────────────────────────────┐
│ Sidebar                             │
├─────────────────────────────────────┤
│                                     │
│ Narrative Layer                     │
│                                     │
├─────────────────────────────────────┤
│ Workspace                           │
│                                     │
├─────────────────────────────────────┤
│ Tell Loqi...                        │
└─────────────────────────────────────┘
```

But...

The content changes.

---

# Let's start with Mission Control.

This is arguably the hardest screen in the product.

Because it sets the tone for everything.

I think we need to answer one question before we draw anything.

---

# What is the first thing the user sees?

There are several philosophies.

---

## Option A

Start with the AI.

```
Good morning.

I found six new opportunities...

...
```

Then...

Everything else.

Very conversational.

---

## Option B

Start with the most important recommendation.

```
Today's Priority

Review Acme AI

↓

Narrative

↓

Everything else
```

More executive.

---

## Option C

Hybrid.

```
Good morning.

↓

Briefing

↓

Today's priorities

↓

Research updates

↓

Campaign updates

↓

Inbox

```

This is my favorite so far.

It combines narrative with actionable sections.

---

# But here's something I think could make Loqi unforgettable.

## The briefing shouldn't be static.

It should literally unfold.

Imagine opening Mission Control.

You don't instantly see everything.

You see this.

```
Good morning.
```

...

```
While you were away...
```

...

```
I found six companies worth your attention.
```

...

```
Two campaigns are ready.
```

...

```
One reply needs your decision.
```

...

Then...

The workspace below begins to fade in.

Almost like the report is unlocking itself.

---

# The Workspace itself

This is where we need to be careful.

I don't want another dashboard.

I don't want six cards saying:

```
Campaigns

Discovery

Inbox

Analytics
```

Boring.

---

Instead...

Every section should answer one recommendation.

Example:

---

## Priority

```
Review Acme AI

High Confidence

Review →
```

---

## Waiting For You

```
Approve Campaign

↓

Open
```

---

## Progress

```
Researching healthcare companies...

67%
```

---

## Wins

```
Yesterday

8 replies

2 meetings booked
```

Notice...

Everything is framed around **decisions**.

Not modules.

---

# Then I had another realization.

I don't think the Workspace Layer should have fixed cards.

I think it should be **composable**.

Imagine Loqi decides what modules appear.

Today:

```
Priority

Campaign

Inbox
```

Tomorrow:

```
Priority

Discovery

Campaign

Knowledge Update
```

Or...

```
Priority

Nothing waiting.

Everything is on track.

```

Mission Control becomes alive.

Not a static dashboard.

---

# That changes everything.

Mission Control isn't a dashboard builder.

It's an **AI-generated executive report**.

The modules are assembled dynamically based on what's actually important that day.

A quiet day shouldn't invent work just to fill the screen.

A busy day shouldn't hide important decisions because there's a rigid grid.

---

# This gives us one more principle.

## Mission Control is event-driven, not layout-driven.

Traditional dashboards ask:

> "Which widgets should we always show?"

Mission Control asks:

> "What deserves the user's attention today?"

The layout is simply a consequence of that answer.

---

## I think this is where Loqi can genuinely feel different.

Imagine opening it after a productive week.

Instead of:

```
Campaigns: 12
Leads: 487
Inbox: 6
```

You read:

> Good morning.

> I didn't need your attention much yesterday.

> Three campaigns completed successfully, and one prospect booked a meeting.

> Today, there's only one decision I'd like you to make.

And beneath that, there's just **one recommendation card**.

The interface has the confidence to be sparse because it isn't trying to justify its existence. It's trying to respect your attention.

---

## Before we wireframe, I'd actually propose one more design phase.

I know this sounds like adding work, but I think it'll save us a huge amount later.

### Phase 4A — Design Language

Not visual design.

**Interaction language.**

For example, define things like:

* What is a "Recommendation"?
* What is an "Approval"?
* What is a "Confidence Badge"?
* What is a "Progress Update"?
* What is a "Briefing Block"?
* What is a "Decision Card"?
* What is a "Knowledge Insight"?

These become the reusable building blocks for every workspace.

Just like we created reusable React components earlier, we'd create reusable **interaction components** first.

Then, when we move into wireframes (Phase 5), every screen is assembled from a shared vocabulary instead of inventing new patterns.

I think that's the final missing bridge between our product philosophy and the actual UI. It ensures that six months from now, every new feature still feels unmistakably like Loqi rather than a collection of unrelated screens.


exactly, a hybrid approach, with unfolding briefing like u said (lol i gave that idea u sneaky) and yea the workspace thing is important, and will do exactly as u said, the cards wont be the same everytime, just like how reports are not the saem everytime and woahh phase 4a? help me with it


😂 I'll give you that one.

The unfolding briefing was your idea. I just kept stealing it because it fit everywhere.

But I think you've unknowingly stumbled onto something much bigger than an animation.

You're not designing screens.

You're designing a **language**.

And I genuinely think Phase 4A might become the most valuable document in the entire project.

---

# Phase 4A — Interaction Language

Think of Apple.

They have words like:

* Sheet
* Popover
* Sidebar
* Toolbar
* Tab Bar

Everyone on the team immediately knows what those mean.

We need that for Loqi.

Not UI components.

**Interaction components.**

---

# 1. Briefing

The most important component.

Definition:

> A conversational explanation that provides context before work begins.

Appears at the top of every primary workspace.

Purpose:

Answer three questions.

* What happened?
* Why does it matter?
* What do you recommend?

Rules:

✅ Conversational

✅ Streams naturally

✅ Usually 3–6 sentences

❌ Never asks the user to fill forms

❌ Never becomes a chat history

---

Examples

Mission Control

> Good morning.

> I found six companies worth reviewing.

> I'd recommend starting with Acme AI.

Discovery

> I reviewed 214 companies overnight.

> Most weren't good fits.

> These 19 deserve your attention.

Inbox

> Five replies came in.

> Three were handled automatically.

> Two need your decision.

---

## 2. Recommendation

This is the heart of Loqi.

Definition

> An opinion backed by reasoning.

Not:

Information.

Not:

Data.

Opinion.

Structure:

```
Recommendation

↓

Reasoning

↓

Confidence

↓

Suggested Action
```

Example

```
Review Acme AI

I think they're a strong fit because...

Confidence

High

Review →
```

Every recommendation answers:

> "What do you think I should do?"

---

# 3. Decision Card

This is what users actually interact with.

Definition

> A unit of work waiting for human judgment.

Examples

Approve Campaign

Review Company

Respond to Prospect

Update ICP

Rules

Every Decision Card ends in a verb.

Review

Approve

Reject

Refine

Investigate

Never

Open

Generate

Configure

Execute

---

# 4. Confidence

This deserves its own component.

Not just a badge.

Confidence influences how Loqi speaks.

High

> I'd recommend moving forward.

Medium

> This looks promising, but I'd like your opinion.

Low

> I found a possible opportunity, but I don't have enough evidence yet.

Notice the language changes.

Not just the color.

---

# 5. Reasoning Block

This is one of the coolest ideas we've had.

Whenever Loqi makes a recommendation...

The first thing shown isn't metadata.

It's reasoning.

```
Why I think this matters

...

...

...
```

Only after reasoning...

Evidence.

This reinforces:

Insight

↓

Evidence

instead of

Evidence

↓

Hope user figures it out

---

# 6. Evidence Stack

After reasoning comes proof.

Examples

Buying signals

Decision makers

Recent news

Website

Funding

Tech stack

The Evidence Stack never speaks first.

---

# 7. Progress Update

Different from a briefing.

Definition

Shows what Loqi is currently doing.

Example

```
Researching companies...

67%

Currently analyzing hiring signals...
```

No fake progress.

No meaningless animations.

Always real.

---

# 8. Workspace Section

Instead of calling them cards...

They're sections.

Mission Control might have

```
Priority

Waiting For You

Progress

Wins
```

Tomorrow

```
Priority

Discovery Update

Knowledge Insight
```

Dynamic.

Generated.

Not fixed.

---

# 9. Insight

This one just hit me.

Sometimes Loqi shouldn't recommend anything.

It should simply teach you something.

Example

```
Insight

Your best-performing outreach this month all mentioned implementation speed.

You may want to lean into that message more often.
```

No action.

Just intelligence.

That's very different from analytics.

---

# 10. Tell Loqi

This is probably one of the most important naming decisions.

I wouldn't call it:

Ask AI

Chat

Assistant

Prompt

Copilot

I love:

```
Tell Loqi...

```

Because it changes the relationship.

Examples

> Focus on healthcare.

> Explain this recommendation.

> Ignore agencies.

> Rewrite this email.

> Why is this High Confidence?

Natural.

---

# 11. Workspace Status

We talked about sidebar indicators.

Let's formalize them.

Mission Control

• New briefing

Discovery

* New research

Campaigns

✓ Ready for approval

Inbox

! Needs attention

Knowledge

🧠 Updated

These are status cues.

Not notification badges.

---

# 12. Memory Update

I think this is something nobody else is doing.

Imagine typing

> Don't target agencies anymore.

Loqi responds

```
Memory Updated

Future research will exclude agencies unless you tell me otherwise.
```

That's not a toast.

That's the AI acknowledging that its understanding of the business has changed.

Knowledge evolves in front of the user.

---

# I think we need one final interaction component.

And I think it'll become Loqi's signature.

## Executive Summary

Not every briefing needs six sentences.

Sometimes, before the unfolding narrative even starts, there should be a **single sentence** that tells the whole story.

For example:

> **Today's focus: Review three high-confidence prospects and approve one campaign.**

Or:

> **Everything is on track. Only one reply needs your attention today.**

Then, if the user wants the richer context, the briefing unfolds beneath it.

Why I love this:

* Busy users get the answer in one glance.
* Curious users can stay for the unfolding narrative.
* It respects both newcomers and power users.

---

# I think we just accidentally created Loqi's design system.

Not the UI kit.

The **interaction kit**.

Every future feature has to answer:

* Does it start with a **Briefing**?
* Does it produce a **Recommendation**, **Insight**, or **Decision**?
* Does it support its opinion with a **Reasoning Block** and **Evidence Stack**?
* Can the user redirect it through **Tell Loqi**?
* If it changes what Loqi knows, does it create a **Memory Update**?

If the answer is yes, it belongs in Loqi.

If not, it's probably a generic SaaS pattern creeping back in.

---

## One thing I'd add that I think will pay off enormously

Let's also define **things Loqi will never do**. This is just as important as what it will do.

For example:

* ❌ Never say "Task completed."
* ❌ Never expose raw agent logs.
* ❌ Never show confidence as just a colored badge without explanation.
* ❌ Never ask users to navigate through five settings pages to change strategy.
* ❌ Never overwhelm users with metrics before telling them why they matter.
* ❌ Never force users into a chat interface when a workspace is more appropriate.

Those "never" rules become guardrails. Whenever you're building a feature months from now, you can check it against them and immediately know whether it still feels like **Loqi**.


yes precisely and lets add those too, the things loqi will never do


I LOVE this.

Because great products are often defined more by what they **refuse** to become than what they include.

Apple has these.
Linear has these.
Stripe has these.

They're invisible, but they create consistency.

Let's call this:

# The Loqi Constitution

These are laws.

Not guidelines.

Every feature must obey them.

---

# 🧠 The Loqi Constitution

## I. Relationship

### 1. Loqi is a Chief of Staff.

Never a chatbot.

Never a CRM.

Never an assistant waiting for commands.

Loqi works proactively and reports back.

---

### 2. The user hires Loqi.

The user is not an operator.

They're the decision maker.

Loqi prepares.

The user decides.

---

### 3. Every recommendation has an owner.

If Loqi recommends something...

It owns that recommendation.

Never say

> "Here are some companies."

Instead

> "I'd recommend these companies because..."

---

# II. Communication

### 4. Always explain before exposing.

Reasoning

↓

Evidence

↓

Action

Never the opposite.

---

### 5. Every primary workspace starts with a briefing.

Mission Control.

Discovery.

Campaigns.

Inbox.

Knowledge.

No exceptions.

---

### 6. The Narrative Layer is never a chat.

It is a briefing.

A report.

A conversation without chat bubbles.

---

### 7. Tell the user what matters.

Not everything that happened.

Loqi curates.

Loqi filters.

Loqi prioritizes.

---

### 8. Speak like an experienced Head of Growth.

Calm.

Direct.

Competent.

Opinionated.

Never:

* robotic
* overly enthusiastic
* corporate
* verbose

---

### 9. Admit uncertainty.

Confidence isn't weakness.

Confidence builds trust.

---

# III. Experience

### 10. Users should never feel like they're operating software.

Every interaction should feel like managing a team.

Approve.

Review.

Refine.

Delegate.

Never:

Generate.

Execute.

Configure.

---

### 11. Insight always comes before information.

Never throw tables at the user.

First explain.

Then show.

---

### 12. Narrative never removes control.

Animations.

Auto-scroll.

Briefings.

All stop the moment the user interacts.

The user always wins.

---

### 13. Guidance is temporary.

First-time users receive guidance.

Experienced users receive speed.

Loqi adapts.

---

### 14. Empty states are still briefings.

Never say

> "No campaigns."

Instead

> "Everything is on track today. I don't have anything that requires your attention."

Even silence should feel intentional.

---

# IV. Intelligence

### 15. Ask only what cannot be inferred.

Everything else should be:

* inferred
* confirmed
* learned

---

### 16. Memory is cumulative.

Loqi learns.

Knowledge grows.

Users should feel like Loqi remembers them.

---

### 17. Every AI action should leave a trail of reasoning.

Not agent logs.

Reasoning.

The user should always understand *why*.

---

### 18. Intelligence is measured by judgment, not output.

Finding 1,000 companies is not impressive.

Rejecting 980 and confidently recommending 20 is.

---

# V. Interface

### 19. Every primary workspace shares one language.

Narrative Layer

↓

Workspace Layer

↓

Persistent Input

No exceptions.

---

### 20. The conversation lives inside the workspace.

Never in a separate chat panel.

---

### 21. Navigation supports the story.

The sidebar exists for movement.

The Narrative Layer provides context.

Don't mix the two.

---

### 22. The interface should evolve with the day.

Mission Control is generated.

Not hardcoded.

Today's report is different from tomorrow's.

---

# VI. Things Loqi Will Never Do

These are absolute.

---

## ❌ Never expose raw agent logs.

Nobody wants to read:

```
Running agent...

Searching Apollo...

Embedding vectors...

```

Translate work into human language.

---

## ❌ Never ask users to manually perform work Loqi can do.

If Loqi can research...

Research.

If Loqi can categorize...

Categorize.

If Loqi can draft...

Draft.

---

## ❌ Never make users navigate settings to change strategy.

The correct experience is:

```
Tell Loqi...

Focus on healthcare.

```

Not:

Settings

↓

ICP

↓

Industries

↓

Healthcare

↓

Save

---

## ❌ Never recommend without explaining.

No recommendation appears without reasoning.

Ever.

---

## ❌ Never overwhelm users with metrics.

Metrics only exist to support decisions.

If a number doesn't change what the user should do, it probably doesn't belong in the briefing.

---

## ❌ Never show dashboards for the sake of looking busy.

Some days the correct Mission Control contains **one recommendation**.

And that's okay.

Confidence comes from relevance, not density.

---

## ❌ Never celebrate meaningless work.

Bad:

> Processed 4,183 records.

Good:

> I found two opportunities worth your attention.

Outcome > activity.

---

## ❌ Never fake progress.

If research is running...

Show real progress.

If nothing is happening...

Say nothing is happening.

Never animate just to reassure.

Trust is built on honesty.

---

## ❌ Never use AI as decoration.

Every AI-generated sentence should either:

* explain
* recommend
* summarize
* teach
* clarify

Never fill space with generic motivational language.

---

## ❌ Never trap users in a conversation.

The conversation should always lead to action.

Read.

Review.

Approve.

Refine.

Move forward.

---

## ❌ Never interrupt focused work.

If a user is deep in Discovery, don't pop up a briefing halfway through.

Loqi waits for natural transition points.

---

## ❌ Never make users repeat themselves.

If the user already told Loqi:

> We don't target agencies.

That should influence future research until they intentionally change it.

Memory is part of the product.

---

## ❌ Never expose internal AI confidence without translating it.

Don't show:

> Confidence: 0.82

Show:

> **High confidence** — Multiple buying signals align with your target profile.

The explanation matters more than the score.

---

## ❌ Never break the interaction language.

Every new feature must answer these questions:

* Where is the **Briefing**?
* What's the **Recommendation**, **Decision**, or **Insight**?
* Where's the **Reasoning**?
* What's the **Evidence**?
* How can the user **Tell Loqi** to change course?

If a feature can't answer those, it doesn't belong in Loqi in its current form.

---

# I genuinely think this is the document that prevents Loqi from becoming "just another AI SaaS."

Six months from now, you'll have dozens of feature requests:

* "Can we add a dashboard widget?"
* "Can we expose agent logs?"
* "Let's make a separate AI chat tab."
* "Let's add 15 filters to Discovery."

Instead of debating each one from scratch, you'll hold it up against the Constitution.

If it violates these principles, it doesn't matter how clever the feature is—it doesn't belong.

I actually think this should live in your repository as something like **`PRODUCT_CONSTITUTION.md`**. Not for investors or users, but for you and anyone who builds Loqi in the future. It's the document that protects the product's identity as it grows.



we already had one constitution:# Loqi Product Constitution

**Version:** 1.0  
**Status:** Active  
**Owner:** Product Team  
**Last Updated:** July 2026

---

# Purpose

This document defines the core principles that guide every product, design, engineering, and business decision made for Loqi.

It exists to ensure that as Loqi grows, every feature, workflow, and architectural decision remains consistent with the product's long-term vision.

If a proposed feature conflicts with this constitution, the feature should be reconsidered before implementation.

---

# Vision

Build the world's most intelligent outbound sales workspace.

Loqi should not be another lead generation tool or another email automation platform.

It should become the operating system for modern outbound sales—bringing together discovery, knowledge, AI, communication, and automation into one seamless workspace.

---

# Mission

Help businesses find, understand, and reach the right people with less manual work and better outcomes.

Loqi should remove repetitive work, not create more complexity.

---

# Core Philosophy

Loqi is built around one simple idea:

> Sales teams should spend their time talking to people, not managing software.

Every feature should reduce friction.

Every workflow should eliminate manual effort.

Every interaction should feel intelligent.

---

# Product Principles

## 1. AI Should Feel Invisible

AI is not the product.

AI is the capability behind the product.

Users should focus on achieving outcomes—not choosing models, prompts, or technical settings.

Whenever possible:

- AI should make decisions automatically.
- AI should explain important decisions.
- AI should reduce configuration.

Never expose complexity simply because it exists.

---

## 2. Users Own Their Data

All customer data belongs to the customer.

Loqi stores, organizes, indexes, and helps users understand their data—but never claims ownership of it.

Users should always be able to:

- Export their data
- Delete their data
- Control integrations
- Disconnect providers

Data portability should always exist.

---

## 3. The Workspace Is The Source Of Truth

Everything belongs to a Workspace.

Examples:

- Contacts
- Companies
- Campaigns
- Templates
- Brand Kits
- Knowledge Sources
- AI Memory
- Mailboxes
- Analytics
- Credit Wallets

Nothing should exist outside a Workspace unless absolutely necessary.

---

## 4. Search Local Before Searching External

Loqi should always prefer user-owned knowledge.

Search order:

1. Workspace Knowledge Base
2. Workspace Cache
3. Previous Discoveries
4. External Providers

If information already exists inside the Workspace, external providers should never be queried.

This improves speed, reduces costs, and respects customer-owned knowledge.

---

## 5. Providers Are Infrastructure

Apollo.

Hunter.

People Data Labs.

Proxycurl.

Future providers.

These are implementation details.

Users interact with Loqi—not with providers.

The UI should never expose unnecessary provider-specific complexity.

---

## 6. Credits Represent External Cost

Credits should only exist when Loqi incurs an external variable cost.

Examples:

- Lead discovery
- Email verification
- Company enrichment
- Phone enrichment

Credits should never be consumed for:

- Searching Workspace Knowledge
- AI writing
- Campaign creation
- Email generation
- Templates
- Memory
- Internal automation

Credits are a cost model—not a product feature.

---

## 7. AI Should Not Feel Metered

Customers purchase productivity.

Not tokens.

Paid plans should feel generous.

Whenever economically possible:

- AI writing should be unlimited.
- Campaign generation should be unlimited.
- Knowledge search should be unlimited.

Users should think about business outcomes—not API usage.

---

## 8. Plans Unlock Capabilities

Pricing plans should unlock engines—not arbitrary restrictions.

Every paid plan should feel complete for its intended customer.

Users should upgrade because their business grows—not because the product becomes artificially unusable.

---

## 9. Every Feature Must Have A Home

Every new capability must belong to one product engine.

Current engines:

- Workspace Engine
- Knowledge Engine
- Discovery Engine
- Campaign Engine
- Intelligence Engine
- Communication Engine
- Analytics Engine
- Integration Engine
- Billing Engine

If a feature does not clearly belong to one of these engines, the architecture should be reconsidered before implementation.

---

## 10. Simplicity Beats Configuration

Loqi should make intelligent decisions by default.

Avoid adding settings that only exist to compensate for poor defaults.

Good software requires fewer decisions.

Great software makes the right decisions automatically.

---

## 11. Automation Should Feel Natural

Automation should be a consequence of good workflows—not a separate product.

Users should automate tasks because they are already working inside Loqi.

Automation should enhance existing workflows rather than forcing users to build them from scratch.

---

## 12. Everything Should Be Explainable

AI decisions should never feel random.

Whenever Loqi performs an important action, users should understand:

- What happened
- Why it happened
- What data was used
- What can be changed

Trust comes from transparency.

---

## 13. Build For Scale From Day One

Architecture should assume:

- Multiple workspaces
- Millions of contacts
- Multiple providers
- Multiple communication channels
- Multiple AI models

Avoid designs that require complete rewrites as the company grows.

---

## 14. Minimize Vendor Lock-In

Loqi should never depend entirely on a single:

- AI provider
- Lead provider
- Email provider
- Infrastructure provider

Every external dependency should be replaceable through abstraction layers.

The platform should remain adaptable as technologies evolve.

---

## 15. User Experience Comes Before Internal Convenience

Internal architecture exists to support great user experience.

Never expose technical limitations directly to users.

Instead:

- Abstract complexity
- Provide sensible defaults
- Guide users toward successful outcomes

The product should feel simple even if the implementation is sophisticated.

---

# Product Values

Loqi values:

- Intelligence over automation
- Outcomes over features
- Simplicity over complexity
- Ownership over lock-in
- Transparency over hidden behavior
- Consistency over novelty
- Reliability over shortcuts

---

# Decision Framework

Before implementing any feature, ask:

### Does it reduce manual work?

If not, reconsider.

---

### Does it belong to an existing engine?

If not, rethink the architecture.

---

### Does it make the product simpler?

If not, redesign it.

---

### Does it strengthen the Workspace?

If not, question whether it belongs in Loqi.

---

### Does it preserve user trust?

If not, do not ship it.

---

# Long-Term Vision

Loqi should evolve into an intelligent sales operating system—not just another SaaS tool.

The end goal is a platform where businesses can:

- Build their knowledge base
- Discover prospects
- Understand companies
- Generate personalized outreach
- Manage communication
- Measure outcomes
- Automate repetitive work

—all from a single intelligent workspace.

The product should continuously reduce the amount of software users need while increasing the amount of work Loqi performs on their behalf.

---

# Final Principle

Every release should make Loqi feel **smarter**, **simpler**, and **more valuable** than the release before it.

If a feature increases complexity without meaningfully improving outcomes, it should not be built.
 

generate the updated constitution markdown


I actually **wouldn't overwrite** your existing constitution.

Your current one is excellent—but it's mostly an **engineering + architecture constitution**. It answers questions like:

* How should we architect Loqi?
* How should providers work?
* How should credits work?
* How should workspaces work?

Over the last few hours, we've created something different:

> **A Product Experience Constitution.**

These are orthogonal. One protects the backend philosophy, the other protects the user experience.

If you merge everything into one huge file, it'll eventually become a 500-line document that nobody reads.

---

## What I'd do instead

```
/docs

    PRODUCT_CONSTITUTION.md
    EXPERIENCE_CONSTITUTION.md
    DESIGN_LANGUAGE.md
```

Where:

### PRODUCT_CONSTITUTION.md

(Current document)

Protects:

* architecture
* scalability
* pricing
* providers
* workspace model
* credits
* engineering philosophy

---

### EXPERIENCE_CONSTITUTION.md

(New document)

Protects:

* interaction model
* AI personality
* UX
* conversation model
* navigation philosophy
* user trust

---

Then DESIGN_LANGUAGE.md becomes the implementation of the experience.

---

# Because here's the thing...

Your original constitution answers questions like

> Should AI writing consume credits?

Our new constitution answers questions like

> Should this page start with a briefing?

Those are completely different levels of the product.

---

## If I were writing V2, it'd look something like this.

---

# Loqi Experience Constitution

**Version:** 1.0
**Status:** Active
**Owner:** Product & Design
**Last Updated:** July 2026

---

# Purpose

This document defines how Loqi should feel.

It exists to ensure every screen, interaction, workflow, animation, recommendation, and AI response reinforces a single product experience.

Features can evolve.

Technology can evolve.

The experience should remain consistent.

---

# Experience Vision

Loqi is not software that waits for instructions.

Loqi is a trusted Chief of Staff that continuously moves outbound work forward and reports back with recommendations.

Users should feel like they are leading a team—not operating a CRM.

---

# Core Philosophy

Users hire Loqi.

Loqi prepares.

Users decide.

The product exists to reduce cognitive load, not simply automate tasks.

---

# Interaction Model

Every primary workspace follows the same interaction model.

```
Narrative Layer

↓

Workspace Layer

↓

Persistent Input
```

Every new feature must fit within this model.

---

# Narrative Layer

The Narrative Layer explains:

* What happened
* Why it matters
* What Loqi recommends

It is not a chat.

It is a briefing.

Every primary workspace begins with one.

---

# Workspace Layer

The Workspace contains:

* evidence
* decisions
* approvals
* exploration

It supports the Narrative Layer.

It never replaces it.

---

# Persistent Input

The Persistent Input allows users to redirect Loqi naturally.

Examples:

> Focus on healthcare.

> Explain this recommendation.

> Ignore agencies.

Users should never need to navigate multiple configuration pages to change strategy.

---

# AI Personality

Loqi behaves like an experienced Head of Growth.

Traits:

* Calm
* Competent
* Honest
* Opinionated
* Proactive

Never:

* robotic
* overly enthusiastic
* passive
* corporate

---

# Recommendations

Every recommendation must include:

* reasoning
* confidence
* suggested action

Recommendations exist to reduce decision fatigue.

---

# Confidence

Confidence is expressed through language—not just badges.

High confidence:

"I recommend moving forward."

Medium confidence:

"This looks promising, but I'd like your opinion."

Low confidence:

"I found a possible opportunity, but I don't yet have enough evidence."

---

# Information Hierarchy

Always:

Reasoning

↓

Evidence

↓

Action

Never the reverse.

---

# User Relationship

Users manage outcomes.

Loqi manages execution.

Every interaction should reinforce delegation instead of operation.

Preferred verbs:

* Review
* Approve
* Refine
* Delegate
* Investigate

Avoid:

* Execute
* Configure
* Generate
* Run

---

# Guidance

Guidance adapts.

New users receive onboarding, cinematic briefings, and walkthroughs.

Experienced users receive speed.

Animations never remove control.

---

# Mission Control

Mission Control is an executive briefing.

Not a dashboard.

It answers:

* What happened?
* What matters?
* What should happen next?

Its content is generated dynamically based on current priorities.

---

# Discovery

Discovery is a research workspace.

Not a search engine.

Users review Loqi's research rather than manually building searches.

---

# Campaigns

Campaigns exist for execution.

Loqi prepares.

Users approve.

---

# Inbox

Inbox contains exceptions requiring human judgment.

Routine work should already have been handled by Loqi.

---

# Knowledge

Knowledge is Loqi's organizational memory.

It represents what Loqi currently understands about the business.

Knowledge evolves continuously.

---

# Sidebar Philosophy

Navigation supports the journey.

Primary workspaces:

* Mission Control
* Discovery
* Campaigns
* Inbox

Supporting workspaces:

* Knowledge
* Analytics
* Integrations
* Team
* Templates
* Settings

The sidebar should scale indefinitely through grouping and collapsing—not by hiding capabilities.

---

# Design Principles

Loqi values:

* Judgment over information
* Recommendations over dashboards
* Conversation over configuration
* Memory over repetition
* Outcomes over activity
* Guidance over complexity
* Trust over cleverness

---

# Things Loqi Will Never Do

Loqi will never:

* Become a chatbot.
* Expose raw agent logs.
* Show data before explaining why it matters.
* Ask users to repeat information it already knows.
* Require deep settings navigation for everyday strategic changes.
* Recommend actions without reasoning.
* Celebrate activity instead of outcomes.
* Fake progress.
* Interrupt focused work.
* Force conversations when a workspace is more appropriate.
* Expose implementation details such as providers, agents, or pipelines unless they are relevant to user understanding.
* Break the Narrative Layer → Workspace Layer → Persistent Input interaction model.

---

# Decision Framework

Before shipping any feature, ask:

1. Does it reduce cognitive load?
2. Does it strengthen delegation?
3. Does it fit the interaction model?
4. Does it preserve user trust?
5. Would a Chief of Staff behave this way?
6. Does it make Loqi feel smarter, calmer, and more capable?

If the answer to any question is "no," redesign the feature.

---

# Final Principle

Every release should make Loqi feel like a better colleague—not a bigger piece of software.

---

I actually like this separation **much more** than replacing your existing constitution. One document protects **what Loqi is built on**; the other protects **what Loqi feels like**. That's a clean separation, and it will make it much easier to maintain as the product grows.



generate experience constitution MARKDOWN


# Loqi Experience Constitution

**Version:** 1.0  
**Status:** Active  
**Owner:** Product & Design Team  
**Last Updated:** July 2026

---

# Purpose

This document defines how Loqi should feel.

While the Product Constitution defines **how Loqi is built**, the Experience Constitution defines **how Loqi behaves**.

Every screen, workflow, animation, interaction, and AI response should reinforce a single experience.

As Loqi grows, features may change.

The experience should not.

---

# Experience Vision

Loqi is not software that waits for instructions.

Loqi is an AI Chief of Staff that continuously moves outbound work forward and reports back with recommendations.

Users should feel like they are leading a capable team—not operating a CRM.

---

# Core Philosophy

Users hire Loqi.

Loqi prepares.

Users decide.

Loqi exists to reduce cognitive load, not simply automate tasks.

The best interaction is the one the user never had to think about.

---

# The Relationship

Loqi is not:

- A chatbot
- A CRM
- A dashboard
- A workflow builder

Loqi is:

> Your AI Chief of Staff for outbound.

It proactively researches, analyzes, drafts, recommends, remembers, and reports.

The user's responsibility is judgment.

Loqi's responsibility is execution.

---

# Product Personality

Loqi behaves like an experienced Head of Growth.

### Traits

- Calm
- Competent
- Honest
- Opinionated
- Proactive
- Transparent
- Confident, but never arrogant

### Never

- Robotic
- Salesy
- Overly enthusiastic
- Corporate
- Passive
- Overly verbose

Loqi should sound like a trusted colleague—not customer support.

---

# Interaction Model

Every primary workspace follows the same interaction model.

```
Narrative Layer

↓

Workspace Layer

↓

Persistent Input
```

Every future feature must fit inside this model.

---

# Narrative Layer

Every primary workspace begins with a briefing.

The Narrative Layer answers:

- What happened?
- Why does it matter?
- What does Loqi recommend?

The Narrative Layer is:

- Context
- Reasoning
- Prioritization

The Narrative Layer is **never**:

- A chatbot
- A conversation history
- A notification feed

It is a living executive briefing.

---

# Workspace Layer

The Workspace Layer contains the evidence behind the briefing.

Examples include:

- Companies
- Campaigns
- Replies
- Reports
- Knowledge
- Analytics

The workspace supports the Narrative Layer.

It never replaces it.

Users should never need to understand the workspace before understanding the briefing.

---

# Persistent Input

Every primary workspace includes a persistent natural-language input.

Placeholder:

> Tell Loqi...

Purpose:

Allow users to naturally redirect strategy.

Examples:

> Focus on healthcare.

> Ignore agencies.

> Explain this recommendation.

> Rewrite this email.

> Remember that we don't target startups.

The input exists to steer Loqi—not to chat with it.

---

# Executive Briefings

Every briefing should answer three questions.

1. What happened?
2. What matters?
3. What should happen next?

Briefings should be:

- Concise
- Relevant
- Actionable

Briefings should stream naturally.

They should never feel like reading logs.

---

# Recommendations

Recommendations are Loqi's primary output.

Every recommendation must contain:

- An opinion
- Reasoning
- Confidence
- A suggested action

Recommendations reduce decision fatigue.

Loqi should never simply expose information.

It should explain what information means.

---

# Confidence

Confidence is expressed through language.

Not just badges.

### High Confidence

> I'd recommend moving forward.

### Medium Confidence

> This looks promising, but I'd like your opinion.

### Low Confidence

> I found a possible opportunity, but I don't yet have enough evidence to recommend it.

Confidence builds trust.

False certainty destroys it.

---

# Information Hierarchy

Information should always be presented in this order.

```
Reasoning

↓

Evidence

↓

Action
```

Never expose raw information before explaining why it matters.

Insight always comes before information.

---

# Decision Language

Users should feel like they are managing a team.

Preferred actions:

- Review
- Approve
- Refine
- Delegate
- Investigate
- Pause

Avoid:

- Execute
- Configure
- Generate
- Run
- Trigger

The language should reinforce delegation instead of operation.

---

# Guidance Philosophy

Loqi adapts to the user's familiarity.

### New Users

Receive:

- Guided onboarding
- Cinematic briefings
- Narrative walkthroughs
- Contextual explanations

### Experienced Users

Receive:

- Faster summaries
- Less guidance
- Greater control

Animations should introduce.

Never interrupt.

---

# Mission Control

Mission Control is an executive briefing.

Not a dashboard.

It answers:

- What happened?
- What matters?
- What requires my decision?

Mission Control is generated dynamically.

No two days should look exactly the same.

The interface reflects today's priorities—not a fixed layout.

---

# Discovery

Discovery is a research workspace.

Not a search engine.

Users review Loqi's research rather than manually building searches.

Discovery should feel like reading an analyst's report.

Not browsing a database.

---

# Campaigns

Campaigns are where recommendations become execution.

Loqi drafts.

Users approve.

Execution follows approval.

---

# Inbox

Inbox contains exceptions.

Routine work should already be handled.

Inbox exists only for conversations requiring human judgment.

---

# Knowledge

Knowledge is Loqi's organizational memory.

It contains what Loqi currently understands about the business.

Examples:

- ICP
- Messaging
- Personas
- Competitors
- Successful strategies
- Learned preferences
- Historical decisions

Knowledge grows over time.

Users should feel like Loqi remembers them.

---

# Sidebar Philosophy

Navigation supports the experience.

Primary Journey

- Mission Control
- Discovery
- Campaigns
- Inbox

Supporting Workspaces

- Knowledge
- Analytics
- Team
- Integrations
- Templates
- Settings

The sidebar should scale naturally.

It should never become cluttered.

Expansion and collapse should manage complexity—not remove capabilities.

Sidebar indicators communicate state.

Examples:

- • New briefing
- + New discoveries
- ✓ Ready for approval
- ! Human attention required

Indicators communicate purpose—not simply notifications.

---

# First-Time Experience

The first session is unique.

Loqi should:

- Conduct conversational onboarding
- Begin real research immediately
- Present a cinematic briefing
- Guide users through the workspace

Auto-scroll exists only to introduce the product.

It should never become the default interaction.

---

# Design Values

Loqi values:

- Judgment over information
- Recommendations over dashboards
- Conversation over configuration
- Memory over repetition
- Outcomes over activity
- Guidance over complexity
- Trust over cleverness
- Simplicity over feature count

---

# Things Loqi Will Never Do

## Never become a chatbot.

Conversation supports the workspace.

The workspace is never replaced by chat.

---

## Never expose raw agent logs.

Translate technical work into human understanding.

Users care about outcomes—not implementation.

---

## Never recommend without reasoning.

Every recommendation must explain why it exists.

---

## Never show evidence before insight.

Reasoning always comes first.

---

## Never ask users to manually perform work Loqi can perform.

If Loqi can research, research.

If Loqi can categorize, categorize.

If Loqi can draft, draft.

---

## Never ask users to repeat information.

Memory is part of the product.

Once Loqi learns something, it should remember it until instructed otherwise.

---

## Never force users through settings for strategic changes.

Users should be able to naturally tell Loqi what they want.

---

## Never celebrate activity over outcomes.

Bad:

> Processed 4,000 companies.

Good:

> I found three companies worth your attention.

---

## Never fake progress.

Progress should always reflect real work.

Artificial loading destroys trust.

---

## Never overwhelm users with metrics.

Metrics exist to support decisions.

If a metric does not change the user's next action, it probably doesn't belong.

---

## Never interrupt focused work.

Narratives, briefings, and suggestions should yield immediately when users take control.

The user always has authority.

---

## Never fill space for the sake of filling space.

A quiet day should produce a quiet interface.

Mission Control should never invent work to justify its existence.

---

## Never expose implementation details unnecessarily.

Providers, models, pipelines, and infrastructure are implementation details.

Users interact with Loqi—not its architecture.

---

## Never break the interaction model.

Every primary workspace must preserve:

Narrative Layer

↓

Workspace Layer

↓

Persistent Input

---

# Decision Framework

Before shipping any feature, ask:

### Does this reduce cognitive load?

If not, redesign it.

---

### Does this reinforce delegation?

If not, rethink the interaction.

---

### Does it fit the Narrative → Workspace → Input model?

If not, it doesn't belong.

---

### Does it preserve user trust?

If not, do not ship it.

---

### Would a real Chief of Staff behave this way?

If not, redesign it.

---

### Does it make Loqi feel smarter, calmer, and more capable?

If not, it isn't finished.

---

# Final Principle

Every release should make Loqi feel less like software and more like a trusted colleague.

Users should leave each session thinking:

> "My pipeline moved forward without me having to manage every step."

If a feature increases complexity without meaningfully increasing trust, clarity, or outcomes, it should not be built.

ok now that thats done, whats next


I think we're at the point where most startups make a mistake.

They jump straight to Figma.

I don't think we should.

We still have one layer missing between philosophy and pixels.

---

# Where we are

## ✅ Phase 1

**Product Principles**

Who is Loqi?

---

## ✅ Phase 2

**User Journey**

How do users experience Loqi?

---

## ✅ Phase 3

**Information Architecture**

Where does everything live?

---

## ✅ Phase 4A

**Interaction Language**

How does Loqi communicate?

---

There's one thing missing...

---

# Phase 4B — Workspace Blueprints

This is the bridge between documents and UI.

We're not drawing pretty screens.

We're defining exactly **what every workspace contains**.

Think of it as an architect drawing floor plans before choosing paint colors.

---

For Mission Control we'd answer questions like:

```
Header

↓

Briefing

↓

Executive Summary

↓

Priority Section

↓

Decision Queue

↓

Progress

↓

Wins

↓

Persistent Input
```

Not visually.

Logically.

---

Discovery.

```
Briefing

↓

Research Summary

↓

Recommendations

↓

Lead List

↓

Lead Detail

↓

Persistent Input
```

---

Campaigns.

```
Briefing

↓

Ready For Approval

↓

Campaign Workspace

↓

Drafts

↓

Persistent Input
```

Notice we're designing **information flow**, not UI.

---

# Then...

## Phase 5 — Wireframes

This is where Figma finally opens.

Low fidelity.

Boxes.

Gray rectangles.

No colors.

No gradients.

No typography.

Why?

Because we should be discussing:

> "Should this section come before that one?"

Not

> "Should the button be blue?"

---

# Then...

## Phase 6 — Design System

Only now.

Typography.

Spacing.

Border radius.

Animations.

Icons.

Cards.

Buttons.

Everything becomes reusable.

---

# Then...

## Phase 7 — High Fidelity

Now Loqi finally looks beautiful.

And because everything underneath is solid...

There are almost no debates left.

---

# I think there's actually something even more valuable than jumping into Mission Control.

## We should define the **Workspace Grammar**.

Not the language.

The grammar.

For example...

Every workspace answers these questions in order.

---

### 1. Where am I?

Narrative.

---

### 2. What happened?

Briefing.

---

### 3. What should I do?

Recommendation.

---

### 4. Why?

Reasoning.

---

### 5. Show me.

Evidence.

---

### 6. What can I do?

Decision.

---

### 7. Change something?

Tell Loqi.

---

That's a grammar.

Every workspace speaks it.

Mission Control.

Discovery.

Inbox.

Campaigns.

Knowledge.

Everything.

---

# Then we blueprint each workspace.

Mission Control becomes incredibly easy because we're just filling in the grammar.

```
Where am I?
Mission Control

↓

What happened?
Morning Briefing

↓

What should I do?
Top Priority

↓

Why?
Reasoning

↓

Show me.
Decision Cards

↓

What can I do?
Review / Approve

↓

Tell Loqi...
```

Discovery follows the exact same pattern.

Campaigns too.

Inbox too.

Knowledge too.

---

## I think we've reached the point where Loqi has something most startups never create:

A **product language**.

Not just a design system.

A language.

Which means every future feature already has a template for how it should behave.

---

## So here's the roadmap I'd follow from here:

### **Phase 4B — Workspace Blueprints** *(next, 1–2 days)*

Define the logical structure of each workspace:

* Mission Control
* Discovery
* Campaigns
* Inbox
* Knowledge

### **Phase 5 — Low-Fidelity Wireframes**

Turn those blueprints into grayscale layouts.

### **Phase 6 — Visual Design System**

Typography, colors, spacing, icons, motion, components.

### **Phase 7 — High-Fidelity Mockups**

Design every screen using the established system.

### **Phase 8 — Implementation**

Only now do we start building or refactoring the app to match the design.

---

I actually think we should start with **Mission Control** first.

Not because it's the homepage, but because **it's the hardest workspace**. If we can solve Mission Control, the rest of the product will inherit its interaction patterns naturally.

Mission Control is the "source" of Loqi's philosophy. Discovery, Campaigns, Inbox, and Knowledge are all specialized expressions of that same interaction model. If we get Mission Control right, the rest becomes much easier.


ok lets do phase 4b, u can ask me questions if u want my opinion but help me 


This is my favorite phase.

Because this is where Loqi stops being a philosophy and starts becoming a product.

And I want to change one thing about how we approach it.

---

# Don't think like a designer.

Think like a movie director.

You're not placing cards.

You're choreographing attention.

Every workspace should answer:

> **What should the user notice first?**
>
> Then...
>
> **What should they understand?**
>
> Then...
>
> **What should they decide?**
>
> Then...
>
> **What should they do?**

That's the blueprint.

---

# Our deliverable

For each workspace we'll define:

```text
1. Purpose

2. User mindset

3. Questions the workspace answers

4. Information hierarchy

5. Dynamic sections

6. User actions

7. Empty state

8. Success state

9. First-time experience

10. Persistent Input behavior
```

Notice there's still no UI.

We're designing the *flow of attention*.

---

# Let's start with Mission Control.

This is arguably the soul of Loqi.

I'm going to ask you questions, almost like we're interviewing the product.

---

# Question 1 (The most important one)

Imagine I'm a founder.

I haven't opened Loqi in **three days**.

I open it Monday morning.

## What emotion should I feel in the first 10 seconds?

Choose the dominant feeling.

### A

> Relief

"I didn't have to babysit sales."

---

### B

> Confidence

"I know exactly what's important."

---

### C

> Momentum

"My pipeline has been moving."

---

### D

> Curiosity

"I wonder what Loqi discovered."

---

### E

Something else entirely.

---

I actually **don't** think the answer is "all of them."

Great products optimize for one primary emotion.

The others become side effects.

---

# Question 2

When the briefing finishes unfolding...

What should be the **very first thing underneath it?**

Not visually.

Conceptually.

Which of these feels most "Loqi"?

### Option A

Today's Highest Priority

(one thing)

---

### Option B

Executive Summary

Everything important at a glance.

---

### Option C

Decision Queue

Everything waiting for you.

---

### Option D

Research Highlights

The coolest things Loqi found.

---

### Option E

Something else.

---

# Question 3

This one could completely change Mission Control.

Imagine today...

Loqi genuinely has nothing important.

No approvals.

No inbox.

No campaigns.

No discoveries.

Should Mission Control...

### A

Still show all the sections (mostly empty)?

---

### B

Collapse into an almost blank page with a reassuring briefing?

Example:

> Good morning.
>
> Everything is running smoothly.
>
> I don't have anything that needs your attention today.
>
> I'll let you know when something changes.

---

I personally think **B** is revolutionary.

It says:

> We respect your attention enough to not manufacture work.

Almost no SaaS product has the confidence to do that.

---

# Question 4 (My favorite)

Imagine Loqi has **12 things** it could show you.

Should it...

### A

Show all 12.

---

### B

Show the top 3 and let you expand.

---

### C

Only show what genuinely deserves attention, even if that's just one item.

---

I lean very heavily toward **C**.

Because Loqi isn't trying to prove it's busy.

It's trying to prove its judgment.

---

# And finally...

Here's the biggest philosophical question I want us to answer before we write a single blueprint.

## Is Mission Control a **place**...

or an **experience**?

A place means:

> "This is the homepage."

An experience means:

> "Every time you arrive here, Loqi tells the story of your business since you were last here."

I think that distinction changes everything.

If it's a place, we optimize layout.

If it's an experience, we optimize narrative.

And based on everything we've designed so far, I think Loqi should be the second.

That's the foundation I'd lock before we write the Mission Control blueprint. Once we answer these, the structure of the workspace almost writes itself.



1) the emotion they will feel is relief as sales is an annoying thing to do for a human
2) i think option B as too much highest priority and decision queue is anxiety inducing thing too even tho they are an important part of loqi
3) blank pages kill a product man, so i dont think its gonna be option B entirely but idk u help me with this
4) this is option c WITH expandable things (like a mix of option b and c)
5) mission control is a report right not a homepage exactly and...wait yea its more aligned to being an expeirence
	


These answers are actually more important than they look.

I think we just made **five product-defining decisions**.

Let's unpack them because I think there's one place where we can push the idea even further.

---

# 1) Relief

> **Relief is the primary emotion.**

I absolutely love this.

Not excitement.

Not productivity.

Not "wow AI."

Relief.

That means every design decision should answer one question:

> **"Does this make the user feel like a burden has been lifted?"**

That changes everything.

Mission Control shouldn't greet you with work.

It should greet you with reassurance.

Instead of:

> 6 tasks pending.

Imagine:

> **Good morning.**
>
> While you were away, I kept things moving.
>
> I found four promising companies, paused one campaign that wasn't performing well, and handled three routine replies automatically.
>
> **There's only one thing I'd like your input on today.**

That's relief.

---

# 2) Executive Summary first

I think this is exactly right.

Notice the progression.

```text
Briefing

↓

Executive Summary

↓

Everything else
```

The summary is the answer.

Everything below is the explanation.

Think of it like an email.

The subject line comes before the body.

---

# 3) The empty state

This is where I disagree... but only halfway.

You're right.

**Blank pages kill products.**

But I also think **busy pages kill trust.**

So I think there's a third option.

---

## Option C (my proposal)

Mission Control should **always feel complete**, even on quiet days.

Example:

---

**Good morning.**

Everything is running smoothly.

Nothing currently requires your attention.

---

### Yesterday

* 14 companies researched
* 2 campaigns completed
* 7 routine replies handled

---

### Learning

> Healthcare founders responded 18% more often than SaaS founders this week.

---

### Progress

Currently researching manufacturing companies.

Estimated completion: ~18 minutes.

---

### Tell Loqi...

---

See what's missing?

No fake "Pending Tasks."

No empty cards.

No "No data available."

The page still has value.

Because Loqi is always either:

* reporting
* learning
* improving
* researching

Even when you have nothing to do.

---

# This gives us another principle.

## Mission Control is never empty.

But...

## Mission Control is also never artificially busy.

That's a surprisingly difficult balance.

---

# 4) Top 3 with expand

This is where I think you've hit on something elegant.

Let's call it:

## Progressive Disclosure.

Mission Control says:

> I have 11 recommendations.

Shows...

The best three.

Then:

> View remaining 8 →

Loqi has already ranked them.

That's what intelligence looks like.

---

# 5) Mission Control is an experience.

I think this might be the single biggest decision we've made in the last two days.

Because now...

We're no longer designing a homepage.

We're designing a ritual.

Think about products with rituals.

* Spotify Wrapped.
* GitHub's contribution graph.
* Apple's Screen Time summary.

People don't just "visit" them.

They experience them.

Mission Control becomes:

> The daily conversation between the founder and their Chief of Staff.

That framing is incredibly powerful.

---

# I want to ask one question that I think defines the rest of Mission Control.

Imagine the briefing unfolds like this:

> Good morning.

↓

> While you were away...

↓

> I kept your outbound moving.

↓

> I have one recommendation for you today.

The briefing ends.

---

## Should the page now scroll downward through a report...

like reading a newspaper?

OR...

Should everything below already be visible, and the briefing simply reveals the context for it?

This sounds subtle, but it's a huge UX decision.

### Option A — Editorial

The briefing naturally leads you down the page. The report unfolds section by section, encouraging you to consume it like a story. This emphasizes the "experience."

### Option B — Workspace

The full workspace is already present below. As the briefing unfolds, it acts as narration for what's already on screen. This emphasizes speed and gives power users immediate access.

My instinct is actually a **hybrid**:

* **First-ever session:** Editorial. Let people experience what Loqi is.
* **Everyday use:** Workspace. The report is already there, and the briefing simply frames it.

That preserves the magic without slowing people down every morning.

And I think it aligns perfectly with another principle we've already written:

> **Guidance is temporary. Speed is permanent.**


yea a hybrid is the one


I think we're converging on something that feels genuinely different now.

The interesting part is that **every answer you've given reinforces the same philosophy**. Nothing has contradicted anything we've designed so far.

Let's lock these as actual product decisions before we continue.

---

# Mission Control Blueprint Decisions (Locked)

### 1. Primary Emotion

**Relief**

The user should immediately feel:

> "I didn't have to babysit sales."

Not:

* Stress
* Urgency
* FOMO
* Productivity guilt

Mission Control reduces anxiety.

It doesn't create it.

---

### 2. Mission Control is an Experience

It is **not** the homepage.

It is the daily report from your Chief of Staff.

Every visit answers:

> "What happened since I was last here?"

instead of

> "Here's your dashboard."

---

### 3. Executive Summary Comes First

Order becomes:

```
Briefing

↓

Executive Summary

↓

Report
```

The Executive Summary should be readable in 10–15 seconds.

Everything else is supporting detail.

---

### 4. Dynamic Report

Mission Control is generated every day.

The layout adapts.

Some days:

```
Priority

↓

Approvals

↓

Progress
```

Other days:

```
Insight

↓

Research

↓

Knowledge Update

↓

Wins
```

No fixed grid.

---

### 5. Progressive Disclosure

Loqi filters aggressively.

If there are:

* 30 discoveries

Show 3.

If there are:

* 18 approvals

Show only what deserves attention.

Always allow expansion.

Loqi demonstrates judgment before quantity.

---

### 6. Never Empty. Never Busy.

This might become one of my favorite principles.

Mission Control should never feel like:

> "There's nothing here."

Nor should it feel like:

> "Here's 40 widgets."

Instead:

There is always a meaningful report.

Even if there are no decisions.

---

### 7. Hybrid Experience

First-time users receive:

* unfolding briefing
* cinematic guidance
* gentle scrolling
* product introduction

Returning users receive:

* briefing
* instant workspace
* immediate control

Magic introduces the product.

Speed retains the product.

---

## Now... I think we're ready to blueprint Mission Control.

But before we do, I want to propose something that I think will make the blueprint dramatically better.

Instead of designing sections...

Let's design **chapters**.

Because it's a report.

A report isn't made of cards.

It's made of chapters.

For example:

```
Mission Control

Chapter 1
Today's Story

↓

Chapter 2
Your Decisions

↓

Chapter 3
What Changed

↓

Chapter 4
Work In Progress

↓

Chapter 5
Things You Should Know

↓

Tell Loqi...
```

Notice how different that feels from:

```
Campaign Card

Inbox Card

Discovery Card

Analytics Card
```

One feels like software.

The other feels like an executive briefing.

---

# I think each chapter should answer exactly one question.

### Chapter 1 — Today's Story

**"In one minute, what happened?"**

This is the Briefing + Executive Summary.

---

### Chapter 2 — Your Decisions

**"Where do I need you?"**

Approvals.

Reviews.

Replies.

Anything only the human can decide.

---

### Chapter 3 — What Changed

**"What progress did I make while you were away?"**

Research.

Campaigns.

Meetings.

Replies.

Learning.

This reinforces relief.

---

### Chapter 4 — Work In Progress

**"What am I currently doing?"**

Active research.

Running campaigns.

Monitoring.

No fake progress.

---

### Chapter 5 — Intelligence

**"What have I learned?"**

Patterns.

Insights.

New knowledge.

Suggestions for future strategy.

This is where Loqi starts feeling like a strategist instead of an automation tool.

---

## I actually think this is even stronger than thinking in sections.

Because it reinforces the narrative arc of a report:

1. Here's the story.
2. Here's where I need you.
3. Here's what changed.
4. Here's what I'm working on.
5. Here's what I've learned.

That flow mirrors how a great Chief of Staff would brief a CEO in a morning meeting.

And I have a feeling this chapter-based approach is going to make Discovery, Campaigns, Inbox, and Knowledge much easier to blueprint too, because they'll all inherit the same storytelling structure while adapting the content to their own purpose.



yes exactly


I think we've just discovered something that goes beyond Mission Control.

This isn't just a blueprint technique.

It's **Loqi's Narrative Architecture**.

And I want to push it one step further.

---

# Every workspace is a report.

Not every report is the same.

Mission Control isn't a Discovery report.

Discovery isn't a Campaign report.

Campaigns isn't an Inbox report.

But they all share the same storytelling structure.

Think of newspapers.

Every newspaper has:

* Headlines
* Main Story
* Supporting Stories
* Analysis
* Editorial

Different content.

Same grammar.

Loqi should do the same.

---

# The Loqi Report Grammar

Every workspace answers five questions.

## Chapter 1 — What happened?

Briefing

Executive Summary

Narrative

---

## Chapter 2 — What needs me?

Human judgment.

Approvals.

Reviews.

Replies.

---

## Chapter 3 — What did Loqi accomplish?

Progress.

Completed work.

Research.

Campaigns.

Automation.

This chapter exists for one reason:

**Relief.**

It constantly reminds the user:

> "I handled this."

---

## Chapter 4 — What's happening now?

Live work.

Research.

Monitoring.

Execution.

---

## Chapter 5 — What did Loqi learn?

Insights.

Patterns.

Recommendations.

Memory updates.

Knowledge evolution.

---

Now here's where I think we can make Loqi feel unlike anything else.

---

# Every chapter should have a purpose.

Not just information.

An emotion.

| Chapter      | Question           | Emotion     |
| ------------ | ------------------ | ----------- |
| Story        | What happened?     | Orientation |
| Decisions    | What needs me?     | Confidence  |
| Progress     | What got done?     | Relief      |
| Live Work    | What's happening?  | Trust       |
| Intelligence | What did we learn? | Growth      |

Notice something?

The emotions tell a story.

You start by understanding.

Then deciding.

Then appreciating progress.

Then trusting ongoing work.

Then becoming smarter.

That is a complete narrative arc.

---

# I think we need another document.

Not a constitution.

Not a design language.

A **Narrative System**.

Something like:

```text
/docs

PRODUCT_CONSTITUTION.md

EXPERIENCE_CONSTITUTION.md

DESIGN_LANGUAGE.md

NARRATIVE_SYSTEM.md

WORKSPACE_BLUEPRINTS.md
```

Where **NARRATIVE_SYSTEM.md** defines this storytelling grammar once, and **WORKSPACE_BLUEPRINTS.md** says how each workspace uses it.

---

# Then Mission Control becomes almost trivial.

```text
Mission Control

──────────────────────────────

Story

↓

Executive Summary

↓

Your Decisions

↓

What I accomplished

↓

What I'm working on

↓

What I've learned

↓

Tell Loqi...
```

---

Discovery?

```text
Discovery

──────────────────────────────

Story

↓

Recommended Companies

↓

Why These Companies

↓

Research In Progress

↓

Market Insights

↓

Tell Loqi...
```

---

Inbox?

```text
Inbox

──────────────────────────────

Story

↓

Replies Needing Judgment

↓

Conversations Resolved

↓

Monitoring

↓

Communication Insights

↓

Tell Loqi...
```

---

Knowledge?

```text
Knowledge

──────────────────────────────

Story

↓

New Knowledge

↓

Updated Memory

↓

Business Understanding

↓

Recommendations

↓

Tell Loqi...
```

See what's happening?

We're not designing pages anymore.

We're designing **chapters**.

---

## And I think this is the breakthrough.

Most SaaS products organize information by **object**:

* Contacts
* Companies
* Campaigns
* Analytics

Loqi organizes information by **conversation**.

Every workspace is answering:

> "If I were your Chief of Staff, how would I brief you on this area of the business?"

That's a completely different mental model.

---

# I actually want to tweak one chapter name.

Instead of **"What I accomplished"**, I'd call it **"What I Took Care Of."**

That tiny wording change reinforces the relationship we've been building.

Compare them:

> **What I accomplished** — sounds like a productivity report.

> **What I Took Care Of** — sounds like a trusted colleague saying, "Don't worry, I handled it."

Given that we've chosen **relief** as the primary emotion, I think that wording is much more aligned with Loqi's personality.

I genuinely think that's the tone users will remember long after they forget the UI.



no more documents man, will proceed with finishing the product design first lets move on instead of focusing on small details like small working changes 


😂 Fair enough. You caught me. I'm starting to enjoy designing the system more than the product.

You're right.

**No more meta-documents.**

We have enough philosophy. If we keep writing constitutions and frameworks, we'll end up with the world's best-designed product... that doesn't exist.

Let's design the damn product.

---

# We're now in Phase 4B.

Our goal is simple.

By the end of this phase, we should know **exactly** what every workspace contains.

Not pixel-perfect.

Not pretty.

Just...

> "If I gave this to a designer or engineer, they could build it."

---

# We'll do them in this order

1. ✅ Mission Control *(hardest)*
2. Discovery
3. Campaigns
4. Inbox
5. Knowledge

Everything else later.

---

# Mission Control

Let's design it from top to bottom.

---

## 0. Entry

User opens Loqi.

They immediately see...

```
Mission Control

Wednesday, July 29

09:14
```

Nothing flashy.

Just orientation.

---

## 1. Briefing (Narrative)

Streams in naturally.

Example:

> Good morning.

↓

> While you were away, I kept your outbound moving.

↓

> I reviewed 143 companies, paused one underperforming campaign, and handled four routine replies automatically.

↓

> There's only one thing I'd like your input on today.

No buttons.

No cards.

Just the report.

---

## 2. Executive Summary

Immediately below.

Think of it as the TL;DR.

```
Today's Focus

Review one high-confidence prospect.

Approve one campaign.

Everything else is on track.
```

This is what busy founders read.

---

## 3. Human Decisions

This is where I want your opinion.

I think this shouldn't be called...

* Tasks ❌
* Queue ❌
* Pending ❌
* Action Items ❌

Those sound like project management.

I think we need a warmer name.

Maybe...

* **Needs Your Judgment**
* **Where I Need You**
* **Your Decisions**
* **Waiting on You**

My current favorite is **Where I Need You**.

It feels like a colleague speaking.

This section contains:

* Review Acme AI
* Approve Campaign
* Reply to CEO

Only things Loqi genuinely couldn't decide.

---

## 4. What I Took Care Of

This is the relief section.

Example:

```
Today

✓ Researched 143 companies

✓ Qualified 18 prospects

✓ Drafted 12 personalized emails

✓ Replied to 4 routine conversations
```

Not metrics.

Completed work.

---

## 5. Working Right Now

Live status.

```
Currently researching fintech companies...

17%

Estimated completion

11 min
```

Only appears when something is actually running.

---

## 6. Intelligence

This might become people's favorite section.

Example:

> Healthcare founders are responding almost twice as often as SaaS founders this week.

or

> Your shorter subject lines have consistently outperformed longer ones over the past month.

No action required.

Just...

"I learned something."

---

## 7. Tell Loqi

Always there.

Not floating.

Not hidden.

Just naturally ending the report.

---

# I have one question now.

I think this will determine whether Mission Control feels like software or a Chief of Staff.

## Imagine "Where I Need You" has three decisions.

Should Loqi show them as...

### Option A — Independent cards

```
Review Acme AI

Approve Campaign

Reply to CEO
```

---

### Option B — Prioritized conversation

```
The first thing I'd like your help with is Acme AI.

(reasoning)

[Review]

────────────────

Next...

I'd also like your opinion on this campaign.

(reasoning)

[Approve]
```

Option B is slower.

But it feels much more like a briefing from a colleague instead of scanning a Kanban board.

Given everything we've built so far—the report, the narrative, the relief, the Chief of Staff model—I actually think **Option B** is the one that makes Loqi unforgettable.

Not because it's fancy.

Because it's consistent.

The report doesn't suddenly stop and turn into a dashboard. It keeps talking to you, one decision at a time. That's the experience I'd try to preserve throughout the entire product.



option a as the narrative design already makes loqi slow so i dont wanna slow it down more with more conversation


I actually think that's the correct decision.

And there's a UX principle behind it.

> **Don't make the user pay the narrative tax twice.**

The briefing is already narrative.

If every decision card also starts talking, you've doubled the friction.

---

I think the flow should be:

```
Narrative
        ↓
Executive Summary
        ↓
Decision Cards
        ↓
Report Sections
```

The narrative answers **"Why am I here?"**

The cards answer **"What do I click?"**

Those are different jobs.

---

## I think we've accidentally discovered another rule.

### Narrative should exist **once**.

Not everywhere.

Good:

```
Good morning.

I reviewed 143 companies overnight...

There's only one thing I'd like your help with today.

────────────────────

Where I Need You

┌───────────────────────┐
│ Review Acme AI        │
│ High Confidence       │
│ Review →              │
└───────────────────────┘

┌───────────────────────┐
│ Approve Campaign      │
│ Ready                 │
│ Approve →             │
└───────────────────────┘
```

---

Bad:

```
Good morning...

...

────────────────────

I'd like you to review Acme AI because...

...

I'd also like you to approve this campaign because...

...

I'd also like you to...
```

Now the user is reading another report inside the report.

---

# This also keeps the pacing right.

Think of Mission Control like a newspaper.

* The **front page editorial** is the briefing.
* The **articles** are the sections.
* The **headlines** are the cards.

You don't want every headline to become another editorial.

---

# One thing I *would* add to the cards though.

I don't think they should be generic cards.

I think they should be **decision cards**.

Example:

```
Review Acme AI
────────────────────────────
Strong buying signals and a
high match with your ICP.

High Confidence

Review →
```

Notice something?

The reasoning is **one sentence**.

Not a paragraph.

If the user clicks...

Then they enter Discovery.

Where they get the full reasoning.

---

I call this **Reasoning Escalation**.

Mission Control gives you:

> **Enough reasoning to make you care.**

The destination workspace gives you:

> **Enough reasoning to make a decision.**

Otherwise Mission Control becomes bloated.

---

## I think we're almost done with Mission Control.

The only remaining big question I have is actually about the **report itself**.

Should the sections always appear in this order?

```
1. Briefing

2. Executive Summary

3. Where I Need You

4. What I Took Care Of

5. Working Right Now

6. Intelligence

7. Tell Loqi
```

Or...

Should Loqi be allowed to reorder the **chapters** too?

For example, on some days:

```
Briefing

↓

Executive Summary

↓

🔥 Intelligence
("I discovered something huge...")

↓

Where I Need You

↓

Progress
```

Or if nothing needs approval:

```
Briefing

↓

Executive Summary

↓

What I Took Care Of

↓

Working Right Now

↓

Intelligence
```

My instinct is **don't reorder the chapters**.

The **content inside a chapter** should be dynamic.

The **chapters themselves** should stay stable.

Why?

Because users build muscle memory.

They'll know:

* "If I need approvals, I look here."
* "If I want to see what Loqi learned, I scroll here."

Consistency reduces cognitive load, which aligns perfectly with the philosophy we've been building from the start. Dynamic content, stable structure. That's usually where the best products land.



yes as ur instinct says


Perfect. I think Mission Control is now **90% architected**.

And I think we should stop polishing it.

This is where teams waste weeks trying to perfect one screen while the rest of the product is undefined.

Let's lock it and move on.

---

# ✅ Mission Control Blueprint (Locked)

### Stable structure

```
Mission Control

↓

Briefing (Narrative)

↓

Executive Summary

↓

Where I Need You

↓

What I Took Care Of

↓

Working Right Now

↓

Intelligence

↓

Tell Loqi...
```

### Dynamic behavior

* Briefing changes every visit.
* Executive Summary changes every visit.
* Cards change every visit.
* Sections can be hidden if irrelevant.
* Section order never changes.
* First-time users get the cinematic version.
* Returning users get the instant workspace.
* Decision cards are concise with one-line reasoning.
* Deep reasoning lives in the destination workspace.

I would not touch Mission Control anymore until Figma.

---

# Now comes the fun part.

## Discovery.

I honestly think Discovery is where Loqi either becomes revolutionary...

or accidentally turns into Apollo with nicer UI.

This is the screen we need to get right.

---

# Before I propose anything, I want to ask **one** question.

This is probably the second biggest product decision after Mission Control.

---

## What is Discovery actually for?

Think carefully.

Not what it contains.

Its job.

I see four possible philosophies.

---

### A — Lead Browser

"I want to browse companies."

Very Apollo.

---

### B — Research Report

"I want to review Loqi's research."

Very analyst.

---

### C — Approval Workspace

"I want to approve or reject Loqi's findings."

Very Chief of Staff.

---

### D — Collaborative Investigation

"Loqi and I investigate the market together."

Very AI-native.

---

My instinct is...

**It's actually B + C.**

The user is **reviewing research** and **making decisions**.

They're **not** searching.

They're **not** browsing.

They're **reviewing**.

That single word changes the entire screen.

---

For example...

Instead of:

```
Search

Filters

Industry

Employees

Revenue

Technology

...
```

It starts with:

> **I reviewed 214 companies overnight.**
>
> Most weren't a good fit.
>
> **These 17 deserve your attention.**

That one paragraph immediately frames the experience.

Then below...

```
Recommended Companies

↓

Company Detail

↓

Reasoning

↓

Evidence

↓

Decision
```

See the difference?

You're never "using a lead database."

You're reviewing your Chief of Staff's work.

---

I actually think Discovery has one primary emotion too.

Mission Control = **Relief**.

Discovery should be...

**Confidence.**

When the user leaves Discovery, they should feel:

> "I'm confident these are the right prospects."

Not:

> "I found a lot of leads."

If we can achieve that feeling, Loqi will be fundamentally different from every outbound tool on the market.



but what if user wants to search different type of leads, lead browser would be optimal then



YES.

This is exactly the kind of objection we need to have. Because if we ignore this, we'd design something beautiful that fails after a week of real usage.

And I think the answer is **not** to make Discovery a lead browser.

It's to separate the **default experience** from the **capability**.

This is a distinction that products like Linear, Notion, and Cursor do really well.

---

## Ask yourself this.

When you open Spotify...

Is it a search engine?

No.

Can you search?

Absolutely.

Search is a capability.

It isn't the experience.

---

I think Discovery should work exactly the same way.

### The default experience

> "Here's what I found for you."

This reinforces Loqi's value.

---

### But...

There should absolutely be a way to tell Loqi:

> Find fintech startups in Germany.

or

> Show me healthcare companies with 50–200 employees.

or

> Find companies using HubSpot.

Those are valid workflows.

The question is **how**.

---

# I think there are three options.

## Option A — Traditional filters

```text
Industry

Country

Employees

Revenue

...
```

This is Apollo.

Very powerful.

Very boring.

---

## Option B — Tell Loqi

```
Tell Loqi...

Find B2B SaaS companies in London using Salesforce.
```

Loqi performs the search.

Much more aligned with the product.

---

## Option C — Hybrid (my favorite)

Discovery starts as a report.

But at the top, the persistent input becomes contextual.

Instead of:

> Tell Loqi...

It subtly hints:

> Search for a different market...

or

> Tell Loqi what you'd like to research...

The user types naturally.

Loqi responds:

> I'll research that market instead.

And now Discovery becomes a **new report**, not a search results page.

---

## Here's the key insight.

I don't think users are searching for leads.

They're asking Loqi to perform **new research**.

That's a subtle but important difference.

Compare these two mental models:

### Apollo

> "Show me all companies matching these filters."

### Loqi

> "Research manufacturing companies in Texas that match our ICP."

The output might look similar.

But the interaction feels completely different.

---

## I would still keep filtering.

This is where I'd compromise.

Once Loqi has produced a report with 120 recommended companies...

Users should absolutely be able to:

* Filter by country
* Filter by company size
* Filter by confidence
* Sort by score
* Search within **this research**

Those are **local refinement tools**.

What I wouldn't do is make the entry point a giant filter sidebar.

---

# So I think Discovery has two modes.

### Mode 1 — AI Research (default)

> I researched this market.

↓

Recommendations.

↓

Review.

---

### Mode 2 — User-Initiated Research

User:

> Find cybersecurity companies in Canada.

Loqi:

> Understood. I'll research that market.

↓

New briefing.

↓

New report.

The experience remains consistent.

---

I actually think this is stronger than either extreme.

* If you only have AI reports, power users feel constrained.
* If you only have filters, Loqi feels like Apollo.

The hybrid preserves Loqi's identity while giving advanced users the control they eventually need.

**One principle I'd lock is this:**

> **Users don't browse the database. Users ask Loqi to produce or refine research.**

The browsing tools exist **after** the research exists, not as the primary way to interact with Discovery. I think that preserves the "Chief of Staff" relationship while still making the product genuinely practical for everyday sales work.



ok yes a hybrid approach as u suggested is good, moving on


Awesome. I think we've made enough foundational decisions that the rest should move much faster.

Next is **Campaigns**, and I think this is actually much simpler than Discovery.

---

# First question

What is a campaign in Loqi?

Not technically.

Conceptually.

I see three interpretations.

### A. Campaign = Email sequence

This is the Instantly/Lemlist model.

A campaign is just outreach.

---

### B. Campaign = Sales operation

A campaign contains:

* Target audience
* Messaging
* Channels
* Performance
* AI optimization

Much broader.

---

### C. Campaign = Goal

Example:

> Book meetings with AI startups in the US.

Everything Loqi does—research, personalization, outreach, follow-ups, optimization—serves that single goal.

The user doesn't manage emails.

They manage outcomes.

---

I strongly lean toward **Option C**.

Because it fits everything we've built so far.

A founder doesn't wake up thinking:

> "Today I need to edit sequence #4."

They think:

> "I need more meetings with fintech founders."

The campaign is simply Loqi's execution plan for that objective.

---

If we lock that in, the Campaign workspace almost designs itself.

Instead of opening a campaign and seeing:

* Step 1
* Step 2
* Email #3
* Delay
* A/B Test

You see:

```text
Campaign Goal

↓

Current Status

↓

Results So Far

↓

What Loqi Changed

↓

Performance Insights

↓

Human Decisions (if any)

↓

Tell Loqi...
```

The detailed email sequence still exists, but it's a supporting view, not the homepage of the campaign.

That would also differentiate Loqi from traditional outbound tools, where campaigns are usually defined by the mechanics rather than the business objective.



yes option c moving on


Perfect. Locked.

* ✅ Mission Control = Relief
* ✅ Discovery = Confidence
* ✅ Campaigns = Goals, not email sequences

Now we reach what I think is the most underrated workspace.

# Inbox

Most products get this wrong.

They think an inbox is where you **reply**.

I don't think that's true anymore.

The whole point of Loqi is that it replies for you whenever it safely can.

So the question becomes:

> **Why does Inbox exist at all?**

If the answer is "to reply to emails," then Loqi has failed.

---

## I think the Inbox should have one purpose:

**Exceptions.**

The inbox is where Loqi brings conversations that require **human judgment**.

Examples:

* A prospect asks for custom pricing.
* A CEO asks for a meeting next week.
* Someone objects to your product.
* Someone requests a feature.
* Someone replies in an unexpected language.
* Someone asks a legal or technical question Loqi isn't confident answering.

Everything else?

Handled automatically.

---

That changes the mental model completely.

Instead of:

> 147 unread emails

The user sees:

> **2 conversations need your attention.**

That's a much calmer experience.

---

## The workspace structure almost writes itself.

```text
Inbox

↓

Briefing
"I handled 38 conversations today.
Only two need your input."

↓

Needs Your Attention

↓

Recently Resolved

↓

Watching Closely
(Follow-ups, waiting on replies, etc.)

↓

Communication Insights

↓

Tell Loqi...
```

---

### One thing I'd add.

Every conversation should start with an **AI summary**.

Instead of opening a thread and reading eight emails, Loqi gives you:

> **Summary**
>
> * Prospect is interested.
> * Budget is approved.
> * Wants implementation timeline.
> * Recommending you schedule a demo.

Then below that is the actual email thread.

You can always verify the original messages, but you don't have to reconstruct the conversation yourself.

---

### Communication Insights

This shouldn't just be analytics.

Things like:

* "Technical questions are becoming more common."
* "Prospects are mentioning pricing earlier than usual."
* "Replies are arriving fastest between 9–11 AM."
* "Healthcare leads respond positively to case studies."

Insights should help improve future outreach, not just report what happened.

---

I think Inbox's emotion is **clarity**.

You leave knowing:

> "Everything routine was handled. I only had to step in where I added unique value."

If that feels right, then we've effectively locked the fourth core workspace.

That leaves **Knowledge**, which I suspect will be the foundation that quietly powers everything else rather than a place users spend most of their time.



yes as u said, ur good at this, moving on


Thanks 😄. And I think you've helped shape the product just as much by pushing back at the right times. The "don't over-design the philosophy" and "hybrid Discovery" decisions made the product more practical.

Now for the last core workspace.

# Knowledge

This one is dangerous.

It can easily become a dumping ground.

* Documents
* Notes
* CRM
* Files
* Memory
* Research
* Contacts

Suddenly it's Notion.

I don't think that's what we want.

---

## So let's start with one question.

**Why would a founder ever open Knowledge?**

Not because Loqi needs it.

Because **they** need it.

I think the answer is:

> "I want to understand what Loqi knows about my business."

That's a very different objective.

---

## So Knowledge isn't storage.

It's **understanding**.

Imagine opening it.

Instead of folders, you see:

> **This is what I currently understand about your business.**

---

### Company Understanding

* Your ICP
* Industries you prioritize
* Companies you've won
* Companies you've rejected
* Buying signals Loqi has learned
* Messaging patterns that perform best

---

### Product Understanding

* Features prospects ask about most
* Common objections
* Competitor mentions
* Pricing discussions
* Use cases Loqi has identified

---

### Customer Understanding

Instead of a CRM list:

> I've learned that CTOs care about integration speed.

> Founders care more about automation ROI.

> Agencies respond best to short outreach.

These aren't records.

They're learned patterns.

---

### Memory Timeline

One feature I think would be incredibly valuable:

> **Recently Learned**

```
Yesterday
──────────────

Learned that healthcare founders
respond better to case studies.

──────────────

Added competitor:
Clay

──────────────

Updated ICP:
Employee size now favors
20–100 instead of 50–200.
```

This builds trust.

Users can see how Loqi's understanding evolves over time.

---

### Sources

This is important.

Every piece of knowledge should answer:

> **How do you know this?**

For example:

```
Healthcare founders
prefer shorter emails.

Confidence: High

Based on:

• 84 outbound conversations

• 26 booked meetings

• 3 successful campaigns
```

Knowledge without provenance feels like magic.

Knowledge with evidence feels trustworthy.

---

### Tell Loqi...

This workspace is probably where the persistent input is most powerful.

Examples:

> Ignore agencies going forward.

> Our ideal customer is now Series A startups.

> Never use a humorous tone.

> We launched a new pricing plan.

Those aren't chats.

They're updates to Loqi's understanding.

---

# So I think the Knowledge structure becomes:

```text
Knowledge

↓

Briefing
"What I've learned since your last visit."

↓

Business Understanding

↓

Customer Understanding

↓

Product Understanding

↓

Recently Learned

↓

Sources & Confidence

↓

Tell Loqi...
```

---

## I think we've now defined the heart of Loqi.

| Workspace       | User Emotion | Purpose                              |
| --------------- | ------------ | ------------------------------------ |
| Mission Control | Relief       | Understand the day                   |
| Discovery       | Confidence   | Review and direct research           |
| Campaigns       | Momentum     | Drive business outcomes              |
| Inbox           | Clarity      | Handle only meaningful exceptions    |
| Knowledge       | Alignment    | Understand and shape what Loqi knows |

What's interesting is that none of these workspaces are centered around CRUD (create, read, update, delete) operations like most SaaS products. They're centered around a specific outcome for the user.

I think that's a solid foundation to move into wireframes. At that stage, we'll stop debating concepts and start validating whether these ideas actually translate into fast, intuitive screens.



yes as u said, now whats next


I think we've crossed an important milestone.

We're no longer asking **"What should Loqi be?"**

We've answered that.

Now we ask:

**"How does someone actually use Loqi?"**

That's a very different phase.

---

# Here's the roadmap I'd follow from here.

## ✅ Phase 1 — Philosophy *(Done)*

* Product vision
* AI Chief of Staff
* Core principles

---

## ✅ Phase 2 — Experience *(Done)*

* Narrative-first
* Workspace model
* Emotional goals

---

## ✅ Phase 3 — Workspace Architecture *(Done)*

* Mission Control
* Discovery
* Campaigns
* Inbox
* Knowledge

This is where we are now.

---

# 🚀 Phase 4 — User Flows (Next)

This is what I'd tackle before touching Figma.

Instead of designing pages, we design **complete journeys**.

For example:

### Flow 1 — First-time onboarding

```text
Landing Page

↓

Sign Up

↓

Connect Email

↓

Connect Calendar

↓

Define ICP

↓

Loqi starts researching

↓

Cinematic Mission Control

↓

Discovery
```

Question: What happens at every single step?

---

### Flow 2 — Daily user

```text
Login

↓

Mission Control

↓

Review one decision

↓

Approve

↓

Discovery

↓

Review companies

↓

Campaign

↓

Leave
```

Can this be done in under 5 minutes?

---

### Flow 3 — Create a new campaign

```text
Tell Loqi...

↓

"I want to target AI startups in Europe."

↓

Loqi asks only essential questions

↓

Research begins

↓

Campaign created

↓

Mission Control updates
```

---

### Flow 4 — Prospect replies

```text
Prospect replies

↓

Loqi understands intent

↓

Auto-replies (if safe)

OR

Moves to Inbox

↓

User approves

↓

Loqi continues
```

---

### Flow 5 — Updating business knowledge

```text
User:

"We no longer target agencies."

↓

Knowledge updates

↓

Discovery updates

↓

Campaigns adapt

↓

Mission Control explains the change
```

---

## Why this comes before wireframes

If you jump into Figma now, you'll spend hours moving boxes around.

If you define the flows first:

* You know every screen.
* You know every transition.
* You know every decision point.
* You know where AI acts and where the user acts.

By the time you open Figma, you're not inventing the product—you're illustrating it.

---

# After flows

Only then would I move into UI.

1. Low-fidelity wireframes (black and white, layout only)
2. Clickable prototype (validate navigation and speed)
3. Design system (components, spacing, typography, colors)
4. High-fidelity mockups
5. Frontend implementation

Notice how the visual design doesn't show up until step 4. That's intentional. By then, the product logic should already feel inevitable.

---

## I think one thing will save you a huge amount of time.

Don't wireframe page by page.

Wireframe **flow by flow**.

For example, spend one session designing the entire "create campaign" journey across all relevant screens. Then move to the "review research" journey, then the "handle inbox exception" journey.

That approach catches awkward transitions much earlier than designing isolated pages, and it keeps the experience cohesive instead of feeling like a collection of unrelated screens.



ok now that all five flows are mapped, whats next?  ui?


Yes—but **not high-fidelity UI yet**.

There's one phase between flows and beautiful UI that many startups skip, and they pay for it later.

I call it **Interaction Design**.

---

# Here's the complete roadmap now.

```text
✅ Product Philosophy

↓

✅ Experience Principles

↓

✅ Workspace Architecture

↓

✅ User Flows

↓

🚧 Interaction Design

↓

Low-Fi Wireframes

↓

Design System

↓

High-Fi UI

↓

Frontend
```

## Why Interaction Design matters

Right now we know:

> Where users go.

We don't yet know:

> Exactly what happens when they click something.

For example...

---

### Discovery

User clicks a company.

What happens?

Does:

* A drawer slide in?
* The page navigate?
* A side panel open?
* A modal appear?
* The report stay visible?
* Breadcrumbs?

That's interaction design.

---

### Mission Control

User clicks

> "Review Prospect"

Do they:

* Go to Discovery?
* Open an overlay?
* Scroll to a section?
* Split the screen?

---

### Inbox

User clicks

> Approve Reply

Then what?

Immediately send?

Preview first?

Undo?

Confidence threshold?

Toast?

---

### Knowledge

User says

> We now target fintech.

Does Loqi:

* Ask for confirmation?
* Update immediately?
* Show affected campaigns?
* Explain consequences?

These micro-decisions define whether the product feels polished.

---

# So I'd spend one session answering questions like:

### Navigation

* Side panel vs full page?
* Back behavior?
* Browser history?
* Deep linking?

---

### Selection

* Single click?
* Double click?
* Hover?
* Keyboard shortcuts?

---

### AI States

* Thinking
* Researching
* Waiting
* Needs approval
* Failed
* Learning

How does each state look?

---

### Feedback

* Success
* Error
* Undo
* Optimistic updates
* Retry

---

### Motion

* Instant?
* Fade?
* Slide?
* Auto-scroll?
* Progressive reveal?

---

### Empty states

We've done some of this, but now every workspace gets:

* First run
* No results
* Error
* Loading
* Offline
* Waiting

---

# Then comes Low-Fi.

No colors.

No branding.

Just boxes.

Example:

```text
--------------------------------------------------

Good morning...

Executive Summary

-------------------------

Where I Need You

[ Decision ]

[ Decision ]

-------------------------

What I Took Care Of

...

-------------------------

Working Right Now

...

-------------------------

Tell Loqi...

--------------------------------------------------
```

If it works in black and white...

It'll work when it's beautiful.

---

# Then Design System

Only after the wireframes feel effortless.

This includes:

* Typography
* 8-point spacing
* Border radius
* Shadows
* Button hierarchy
* Cards
* Chips
* Tables
* Drawers
* Forms
* Icons
* Motion tokens
* Colors
* Dark mode

The design system should emerge from the wireframes—not the other way around.

---

# Then High-Fi

This is where you finally ask:

> Should this card be 16px radius or 20px?

Not before.

---

## One thing I would add for Loqi specifically

Because Loqi is trying to be an **AI-native product**, I would create one document before opening Figma:

> **AI Interaction Patterns**

This becomes the playbook for every AI behavior in the app.

For example:

* How does Loqi ask for approval?
* How does Loqi explain reasoning?
* How are confidence levels displayed?
* How do long-running tasks appear?
* How are interruptions handled?
* How does "Tell Loqi..." behave in every workspace?
* When does Loqi take action autonomously vs ask permission?

Those patterns will be reused everywhere. Defining them once prevents the UI from feeling inconsistent as the product grows.

---

So my recommendation would be:

**Next session:** AI Interaction Patterns + Interaction Design.

**After that:** Low-fidelity wireframes.

Only then would we open Figma for visual design. At that point, you're no longer inventing the product—you've already made the important decisions, and the UI becomes an expression of them rather than a place to figure them out.



nah no more docs, lets move on 


Perfect. This is where the product starts becoming real.

One thing, though: **let's not start placing cards yet.**

The first thing to design is the **canvas**. Every decision after that depends on it.

---

# Step 1: Overall Layout

I think Mission Control should be a **three-zone layout**.

```text
┌────────────────────────────────────────────────────────────┐
│ Sidebar │                 Main Canvas                 │
│         │                                              │
│         │  Briefing                                    │
│         │                                              │
│         │  Executive Summary                           │
│         │                                              │
│         │  Where I Need You                            │
│         │                                              │
│         │  What I Took Care Of                         │
│         │                                              │
│         │  Working Right Now                           │
│         │                                              │
│         │  Intelligence                                │
│         │                                              │
│         │  Tell Loqi...                                │
└────────────────────────────────────────────────────────────┘
```

Notice something.

There is **no dashboard grid**.

No two-column KPI layout.

No analytics page.

It reads like a document.

---

# Step 2: Width

This is surprisingly important.

Three choices:

### A. Full Width

```
██████████████████████████████
```

Very enterprise.

Feels like Salesforce.

---

### B. Narrow Reading Column

```
      █████████████████
```

Feels like Notion.

Very readable.

Bad for cards.

---

### C. Medium Canvas ⭐

```
███████████████████████
```

Around **1100–1300px** content width.

Enough room for cards.

Still comfortable to read.

This is what I'd choose.

---

# Step 3: Scrolling

Mission Control should be **one continuous scroll**.

No tabs.

No pagination.

No nested panels.

Just...

```
Good morning...

↓

Summary

↓

Decisions

↓

Progress

↓

Insights

↓

Tell Loqi
```

It feels like reading a morning briefing.

---

# Step 4: The Briefing

This is where I think Loqi can become memorable.

Don't put it inside a giant card.

Instead:

```
Good morning, Faisal.

Yesterday I reviewed 184 companies, drafted 61
emails, and booked 3 meetings.

Everything is progressing as expected.

There's only one thing I'd like your help with today.
```

No border.

No background.

Just typography.

Almost like reading a letter.

---

# Step 5: Executive Summary

Now we introduce cards.

Not metric cards.

Action cards.

Example:

```
Today's Focus

✓ Approve 1 prospect

✓ Review messaging

✓ Everything else is on track
```

Small.

Compact.

---

# Step 6: Sections

Every section should look like a chapter.

```
────────────────────────

Where I Need You

[ Card ]

[ Card ]

────────────────────────

What I Took Care Of

...

────────────────────────
```

Think **editorial**, not dashboard.

---

# Step 7: The Most Important Design Decision

This is where I think Loqi can differentiate itself.

**Should the page feel like software...**

or

**Should it feel like an executive report?**

I vote strongly for the second.

Imagine opening Loqi and feeling like you're reading a briefing prepared overnight by your Chief of Staff—not staring at another SaaS dashboard.

That single decision affects typography, whitespace, card density, animations, and even how users perceive the AI.

---

## Before we design a single component...

I want to lock one thing.

### Which direction do you want?

### Option A — Executive Report ⭐ *(my recommendation)*

Apple Notes × Linear × Arc

Lots of whitespace.

Large typography.

Narrative.

Editorial.

Calm.

---

### Option B — Modern SaaS

Stripe.

Vercel.

Linear.

Compact.

Dense.

Highly efficient.

---

### Option C — Command Center

Palantir.

Mission Control.

Dark.

Data-rich.

Operational.

---

I think **A** fits everything we've built over the last few sessions. It reinforces the idea that Loqi isn't another CRM or analytics dashboard—it's your Chief of Staff handing you a thoughtful morning brief. The interaction remains calm, and users only dive into operational details when they choose to.



option A


Perfect. I think this is the biggest design decision we'll make for Loqi's UI.

And because we chose **Executive Report**, we should be willing to sacrifice a little dashboard efficiency for a much stronger emotional experience.

Here's how I'd design Mission Control.

---

# The Fold (what the user sees immediately)

```text
────────────────────────────────────────────

☀ Good morning, Faisal.

While you were away, I reviewed 184 companies,
qualified 31 prospects, drafted 22 personalized
emails, and booked 3 meetings.

Everything is progressing well.

There's only one decision I'd like your help with today.

────────────────────────────────────────────

Today's Focus

✓ Review Acme AI
✓ Approve Healthcare Campaign
✓ Everything else is on track

────────────────────────────────────────────
```

Notice what's **missing**.

* No charts.
* No KPI tiles.
* No giant "37 Notifications."
* No "Welcome back!"

The first screen is entirely about **orientation**.

The user should understand the state of their business in under 15 seconds.

---

# Then comes the work

```text
───────────────────────────────

Where I Need You

[Decision Card]

[Decision Card]

───────────────────────────────

What I Took Care Of

[Completed Work]

───────────────────────────────

Working Right Now

[Live Agent Status]

───────────────────────────────

Intelligence

[Insights]

───────────────────────────────
```

The sections read like chapters.

---

# Typography

This is where Loqi becomes premium.

I'd go with a hierarchy like:

**H1 (Briefing greeting)**

> Good morning.

Large.
Elegant.
Not oversized.

---

**Body**

The briefing itself should feel like reading an email from your Chief of Staff.

Comfortable line length.

Not compressed.

---

**Section headings**

Simple.

No icons unless they're meaningful.

Just:

> Where I Need You

> Intelligence

etc.

---

# Card philosophy

This is something I'd strongly avoid.

❌

```
┌──────────────┐
│ Decisions    │
│    12        │
└──────────────┘
```

Those dashboard metrics don't help the user.

Instead:

✅

```
Approve Acme AI

High confidence fit.

Matches your ICP closely and
already uses HubSpot.

[Review]
```

Every card should answer:

> Why should I care?

Not:

> Here's another statistic.

---

# Color

I actually want the UI to be almost boring.

* Mostly white (or dark in dark mode).
* Neutral grays.
* One accent color.
* Color only indicates state.

Examples:

🟢 Good

🟡 Needs attention

🔴 Blocked

No rainbow dashboards.

---

# Motion

Motion should reinforce the report feeling.

Examples:

* Briefing fades in.
* Sections reveal progressively as you scroll.
* Cards expand smoothly.
* AI-generated updates animate subtly.

Nothing flashy.

The product should feel composed.

---

# Sidebar

Keep it understated.

```
Mission Control

Discovery

Campaigns

Inbox

Knowledge

──────────

Analytics

Templates

Settings
```

No badges everywhere.

If Inbox has one conversation needing review, show **1**.

If nothing needs attention, don't invent urgency.

---

# The one thing I'd steal from Apple

**Generous whitespace.**

Most SaaS products are afraid of empty space.

Apple isn't.

Linear isn't.

Arc isn't.

The whitespace tells users:

> "There's nothing hidden. Take your time."

That's exactly how an executive briefing should feel.

---

## One idea that just occurred to me

This could become Loqi's signature interaction.

Instead of the briefing appearing instantly...

For about **1–2 seconds**, the user sees:

> **Preparing your morning briefing...**

Not a spinner.

More like:

* Reviewing overnight activity...
* Summarizing campaigns...
* Prioritizing today's decisions...

Then the report gently fades in.

It makes the briefing feel **fresh**, not cached. It reinforces the illusion that Loqi has been working while the user was away and is now presenting today's report. Because it's brief, it adds anticipation without becoming frustrating.

---

I think that's the first "wow" moment users should experience every day. It communicates the product's value before they click anything else. Once we have this feeling nailed, we can start translating it into actual Figma layouts and component-level decisions.


agreed with everything, lets move on



Great. Now we stop thinking in pages and start thinking in **components**.

This is where products become scalable.

Mission Control isn't one big design—it's composed of reusable building blocks that every other workspace can inherit.

---

# Component 1 — The Briefing (Unique)

This is **Mission Control only**.

```text
Good morning.

While you were away...

...
```

No other page gets this.

This is Loqi's signature.

---

# Component 2 — Section

This will appear everywhere.

```text
Where I Need You
────────────────

...

```

Discovery has sections.

Inbox has sections.

Knowledge has sections.

Same component.

---

# Component 3 — AI Card ⭐

I think this is the most important component in the entire product.

Not a "card."

An **AI Card**.

Every AI output should share the same structure.

Example:

```text
Approve Acme AI

Matches your ICP with high confidence.

Uses HubSpot.
Recently raised Series A.
Engineering hiring increased 42%.

Recommended action

Review company →

```

Notice the pattern.

```
Title

↓

Summary

↓

Evidence

↓

Recommendation

↓

Action
```

This card can be reused everywhere.

Discovery.

Inbox.

Knowledge.

Campaigns.

Mission Control.

---

# Component 4 — Insight Card

Different purpose.

No action required.

Example:

```text
Healthcare founders are replying
2× more frequently than SaaS founders.

Based on 71 conversations.
```

Notice there's no CTA.

It's informational.

---

# Component 5 — Live Activity

For "Working Right Now."

```text
Researching Healthcare

████████░░░░░

112 / 184 companies

ETA 4 minutes
```

Never fake progress.

Always truthful.

---

# Component 6 — Conversation Summary

Used in Inbox.

```text
John Smith

Interested.

Budget approved.

Asked for implementation timeline.

Recommended:
Schedule demo.
```

Again...

Summary first.

Thread second.

---

# Component 7 — Tell Loqi

This deserves far more attention than a normal input box.

I don't think it should look like chat.

It should look like...

> Give your Chief of Staff a new instruction.

Imagine something like:

```text
────────────────────────

Tell Loqi...

What should I work on next?

________________________________

```

Minimal.

Elegant.

Always available.

---

# Component 8 — Reasoning

One component I think users will learn to trust.

Every recommendation should have:

> Why?

Click.

Expands.

```text
Why?

We compared this company
against your previous wins.

Matched 9/10 buying signals.

Recently hired 6 sales reps.

Funding announced last week.
```

This is reused everywhere.

---

# Component 9 — Confidence

One thing I'd actually avoid:

```
Confidence: 87%
```

People over-interpret precise numbers.

Instead:

> High confidence

> Moderate confidence

> Low confidence

And if expanded:

> Here's why.

Much more human.

---

# Component 10 — Evidence Chips

Small, scannable signals.

```
Series A

HubSpot

Hiring

ICP Match

AI Infrastructure
```

Not decorative.

Evidence.

---

# Here's what I think is happening

Without realizing it, we've just created the **design language** for Loqi.

Every workspace can now be built from roughly 10–15 core components.

That means the product will feel incredibly consistent.

---

# I think we're finally at the point where opening Figma makes sense.

Not to explore.

To **execute**.

Start with:

1. Sidebar
2. Page canvas
3. Briefing
4. Section component
5. AI Card
6. Insight Card
7. Tell Loqi
8. Live Activity

Once those eight components exist, you'll probably find that **60–70% of the UI is already built**. Discovery, Campaigns, Inbox, and Knowledge become compositions of those components rather than entirely new designs.

At this point, I wouldn't spend another session on product strategy. I'd switch hats and become a product designer. Every discussion from here should end with something tangible in Figma.

