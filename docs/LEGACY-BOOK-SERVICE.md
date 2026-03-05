# Polly Connect - Legacy Book Service

## How It Works

Polly captures family stories through natural voice conversations over 6-12 months.
Each answer is automatically tagged with a Jungian narrative bucket (Hero's Journey stage)
and life phase. The system steers future questions toward gaps in the story arc, so over time
the full narrative of a person's life fills in naturally.

When enough memories are collected (~90+), the system assembles them into chapter outlines
and uses AI to weave raw memories into polished narrative prose -- a real book.

## Data Flow

```
Voice conversation (ESP32 device)
  -> Story recorded (stories table)
  -> MemoryExtractor tags: people, locations, emotions, life phase, Jungian bucket
  -> Structured memory saved (memories table)
  -> NarrativeArc tracks coverage across 6 buckets
  -> EngagementTracker steers next questions toward gaps
  -> EchoEngine (ECHO-BRIDGE-INVITE) keeps speaker talking naturally
  -> BookBuilder groups memories into chapters by bucket + life phase
  -> OpenAI generates chapter prose from memory clusters
  -> Chapter drafts saved (chapter_drafts table)
  -> Family reviews/edits on web portal
  -> Export to PDF for printing
```

## Jungian Narrative Buckets (Hero's Journey)

| Bucket | What It Covers | Example Questions |
|--------|---------------|-------------------|
| Ordinary World | Everyday life, childhood, family rhythms | "What did a normal day look like?" |
| Call to Adventure | Moments that changed everything | "When did you realize things were different?" |
| Crossing Threshold | Big decisions, no going back | "What was the hardest decision you made?" |
| Trials/Allies/Enemies | Hard times, who helped, who didn't | "Who stood by you when it got tough?" |
| Transformation | How you changed, what you became | "How were you different after all that?" |
| Return with Knowledge | Wisdom, lessons, legacy | "What would you tell your grandkids?" |

Questions and answers are bucketed AUTOMATICALLY on intake -- not rearranged later.
The system uses keyword heuristics (no ML required) to classify each memory.
As gaps appear (e.g., no "transformation" stories), the question engine prioritizes
those areas in future conversations.

## Chapter Structure

Target: 14-20 chapters, 150-200 pages.

Chapters are organized by bucket + life phase:
- "Where It All Started" (ordinary_world / childhood)
- "The Kitchen Table" (ordinary_world / childhood)
- "Growing Up" (ordinary_world / adolescence)
- "When Things Changed" (call_to_adventure / adolescence)
- "Stepping Out" (call_to_adventure / young_adult)
- "The Decision" (crossing_threshold / young_adult)
- "Love and Beginnings" (crossing_threshold / young_adult)
- "The Hard Years" (trials / adult)
- "Who Stood By Me" (trials / adult)
- "Raising a Family" (trials / adult)
- "How I Changed" (transformation / adult)
- "Finding My Way" (transformation / midlife)
- "What I Know Now" (return_with_knowledge / reflection)
- "For the Grandkids" (return_with_knowledge / reflection)

Each chapter needs 5+ memories to be "ready." Large groups split into parts automatically.
Chapters can always receive more memories even after a draft is generated -- just regenerate.

## How OpenAI Handles Book Generation

OpenAI (GPT-4o) is used ONLY for prose generation, not for classification or structure.
The Jungian structure is handled by pure Python heuristics (MemoryExtractor + NarrativeArc).

When a chapter draft is requested:
1. BookBuilder pulls all memories for that chapter's bucket + life phase
2. Builds a prompt with the memories, emotions, and chapter context
3. OpenAI writes 7-10 paragraphs of warm, narrative prose
4. The draft preserves the speaker's voice and emotional tone
5. Family can edit the draft on the web portal before finalizing

Cost per chapter: ~$0.02-0.05 (GPT-4o). Full book: ~$0.50-1.00.

## Service Tiers

### Tier 1 -- Free (Included with Polly Device)
- Voice captures stories automatically over months
- Families see progress on the web dashboard (bucket coverage, memory count)
- Raw transcripts viewable and verifiable by family members
- AI-guided question selection fills narrative gaps naturally
- No cost beyond the Polly device itself

### Tier 2 -- Legacy Book ($49-$99)
- Available after ~90 memories collected (typically 6-12 months)
- AI assembles chapters using the Jungian arc structure
- Family reviews and edits chapter drafts on web portal
- Generate formatted PDF with chapter titles, sections, and page numbers
- Send to print-on-demand (Lulu, Blurb, or Amazon KDP)
- Ship a physical hardcover or softcover book to the family
- Includes 1 printed copy
- **Our cost**: ~$15-25 print + ~$1 AI generation = ~$16-26
- **Margin**: $23-73 per book

### Tier 3 -- Premium Legacy Package ($149-$249)
- Everything in Tier 2, plus:
- Professional human editor reviews AI drafts for tone and flow
- Custom book cover designed with family photos
- 3 printed copies (additional copies at cost, ~$15-20 each)
- Audio companion: original voice recordings linked via QR codes in the book
- Dedication page and family tree page
- Premium binding (hardcover, dust jacket)
- **Our cost**: ~$60-80 (editing + 3 copies + cover design)
- **Margin**: $69-169 per package

### Add-Ons
- Additional printed copies: $20-25 each
- Leather-bound edition: +$40-60
- Digital audiobook (compiled voice recordings): $29
- Annual subscription (ongoing story capture + yearly book update): $39/year

## Revenue Projections (Per Device Sold)

| Scenario | Year 1 | Year 2+ |
|----------|--------|---------|
| Device only (Tier 1) | $0 | $0 |
| Standard book (Tier 2) | $49-99 | $39/yr subscription |
| Premium package (Tier 3) | $149-249 | $39/yr + extra copies |

Average expected revenue per active device: ~$75-100 in year 1.

## Implementation Status

- [x] MemoryExtractor -- tags memories on intake
- [x] NarrativeArc -- tracks bucket coverage, suggests questions
- [x] EchoEngine -- ECHO-BRIDGE-INVITE follow-up system
- [x] EngagementTracker -- intelligent question selection
- [x] BookBuilder -- chapter outline + AI draft generation
- [x] Database tables -- stories, memories, chapter_drafts
- [x] Web portal -- book progress dashboard
- [x] Web portal -- chapter list with status
- [x] Web portal -- chapter view/edit
- [x] Web portal -- regenerate chapter drafts
- [ ] PDF export with formatting
- [ ] Print-on-demand integration
- [ ] Payment/ordering system
- [ ] Audio QR code companion
- [ ] Professional editor workflow
