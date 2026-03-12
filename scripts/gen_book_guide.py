"""
Generate a layman's guide PDF explaining how the Polly Connect Legacy Book works.
Run on EC2: python3.11 scripts/gen_book_guide.py
"""
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak


def build():
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=1*inch, bottomMargin=1*inch,
                            leftMargin=1*inch, rightMargin=1*inch)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='GuideTitle', fontName='Helvetica-Bold', fontSize=24,
        leading=30, alignment=TA_CENTER, spaceAfter=12,
        textColor=HexColor('#1a1a1a'),
    ))
    styles.add(ParagraphStyle(
        name='GuideSubtitle', fontName='Helvetica-Oblique', fontSize=14,
        leading=18, alignment=TA_CENTER, spaceAfter=36,
        textColor=HexColor('#555555'),
    ))
    styles.add(ParagraphStyle(
        name='SectionHead', fontName='Helvetica-Bold', fontSize=16,
        leading=22, alignment=TA_LEFT, spaceBefore=24, spaceAfter=10,
        textColor=HexColor('#2d6a4f'),
    ))
    styles.add(ParagraphStyle(
        name='SubHead', fontName='Helvetica-Bold', fontSize=13,
        leading=17, alignment=TA_LEFT, spaceBefore=16, spaceAfter=6,
        textColor=HexColor('#333333'),
    ))
    body = ParagraphStyle(
        name='GuideBody', fontName='Helvetica', fontSize=11,
        leading=16, alignment=TA_JUSTIFY, spaceAfter=8,
        textColor=HexColor('#1a1a1a'),
    )
    styles.add(body)
    styles.add(ParagraphStyle(
        name='GuideBullet', fontName='Helvetica', fontSize=11,
        leading=16, alignment=TA_LEFT, spaceAfter=4,
        leftIndent=24, bulletIndent=12,
        textColor=HexColor('#1a1a1a'),
    ))
    styles.add(ParagraphStyle(
        name='Footer', fontName='Helvetica-Oblique', fontSize=9,
        leading=12, alignment=TA_CENTER, spaceBefore=36,
        textColor=HexColor('#999999'),
    ))

    s = []

    # Title page
    s.append(Spacer(1, 100))
    s.append(Paragraph("How Your Legacy Book Is Made", styles['GuideTitle']))
    s.append(Paragraph("A Plain-English Guide to the Polly Connect Book Pipeline", styles['GuideSubtitle']))
    s.append(Spacer(1, 40))
    s.append(Paragraph(
        "This guide explains, step by step, how the stories you tell Polly "
        "get turned into a real, printed legacy book &mdash; complete with photos "
        "and QR codes that play back your actual voice recordings.",
        styles['GuideBody'],
    ))
    s.append(PageBreak())

    # Step 1
    s.append(Paragraph("Step 1: You Tell Your Stories", styles['SectionHead']))
    s.append(Paragraph(
        "Everything starts when you talk to Polly. You press the button (or say the wake word) "
        "and share a memory &mdash; maybe a story about your childhood, a funny moment with "
        "your kids, or what life was like growing up. Polly listens, records your voice, and "
        "converts your words to text using speech-to-text technology.",
        styles['GuideBody'],
    ))
    s.append(Paragraph(
        "Each story gets saved with three things: (1) the written text of what you said, "
        "(2) your original voice recording as an audio file, and (3) any photo you linked "
        "to that story through the web portal.",
        styles['GuideBody'],
    ))

    # Step 2
    s.append(Paragraph("Step 2: Stories Become Memories", styles['SectionHead']))
    s.append(Paragraph(
        "Behind the scenes, each story you tell gets analyzed and stored as a \"memory\" in "
        "the database. Think of a memory as a building block for your book. The system looks "
        "at each memory and figures out two things:",
        styles['GuideBody'],
    ))
    s.append(Paragraph("&bull; <b>Life Phase</b> &mdash; When in your life did this happen? "
        "(Childhood, Adolescence, Young Adult, Adult, Midlife, Elder, or Reflection)", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Story Arc Bucket</b> &mdash; What role does this memory play in your life story? "
        "Using a storytelling framework inspired by the \"Hero's Journey,\" each memory is placed into one of six buckets: "
        "Everyday Life, Turning Points, Big Decisions, Challenges &amp; Helpers, How You Changed, or Wisdom &amp; Lessons.", styles['GuideBullet']))

    # Step 3
    s.append(Paragraph("Step 3: Memories Get Organized into Chapters", styles['SectionHead']))
    s.append(Paragraph(
        "Once you have enough memories, the system automatically groups them into chapter outlines. "
        "It sorts them first by life phase (childhood first, reflection last) and then by story arc. "
        "If a single group has more than 10 memories, it splits them into multiple chapters so each "
        "one stays a comfortable reading length.",
        styles['GuideBody'],
    ))
    s.append(Paragraph(
        "Each chapter gets a title like \"Childhood &mdash; Everyday Life\" and a list of which "
        "memories belong in it. You can see all of this on the Book page in the web portal.",
        styles['GuideBody'],
    ))

    # Step 4
    s.append(Paragraph("Step 4: AI Writes the Chapter Drafts", styles['SectionHead']))
    s.append(Paragraph(
        "Here is where the magic happens. When you click \"Generate Draft\" on a chapter, "
        "the system sends all the memories for that chapter to OpenAI's GPT-4o. The AI reads "
        "through your stories and weaves them together into a flowing, readable chapter &mdash; "
        "written in first person, in your voice.",
        styles['GuideBody'],
    ))
    s.append(Paragraph(
        "The AI does not make things up. It uses only the stories you actually told. It just "
        "reorganizes them, adds transitions, and polishes the language so it reads like a "
        "real book chapter instead of a collection of separate recordings.",
        styles['GuideBody'],
    ))
    s.append(Paragraph(
        "You can review the draft, edit it if you want, or regenerate it. The draft is saved "
        "so you do not lose it.",
        styles['GuideBody'],
    ))

    s.append(PageBreak())

    # Step 5
    s.append(Paragraph("Step 5: Photos and QR Codes Get Attached", styles['SectionHead']))
    s.append(Paragraph(
        "As you upload photos through the web portal, you can link them to specific stories. "
        "Each story also has its original voice recording. The book system uses both of these "
        "to enrich your printed book:",
        styles['GuideBody'],
    ))
    s.append(Paragraph("&bull; <b>Inline Photos</b> &mdash; If a story has a linked photo and "
        "the \"Include photo in printed book\" toggle is on, that photo appears right in the "
        "chapter where the story is told.", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>QR Codes</b> &mdash; If a story has a voice recording and "
        "the \"Include QR in book\" toggle is on, a scannable QR code is printed underneath "
        "the photo (or by itself if there is no photo). Anyone with a phone can scan it "
        "and hear the original voice recording.", styles['GuideBullet']))
    s.append(Paragraph(
        "You control exactly what goes in the book. Some stories might get a photo and a QR code, "
        "some might get just a QR code (so readers can hear the voice but the photo is not in the book), "
        "and some might be pure text with no media at all. This keeps it feeling like a legacy memoir, "
        "not a photo album.",
        styles['GuideBody'],
    ))

    s.append(Paragraph("No Duplicates", styles['SubHead']))
    s.append(Paragraph(
        "Since multiple chapters can reference the same group of memories (especially when you have "
        "a lot of childhood stories), the system makes sure each photo and each QR code only "
        "appears <b>once</b> in the entire book &mdash; in the first chapter where it is relevant. "
        "No duplicates, no repeats.",
        styles['GuideBody'],
    ))

    # Step 6
    s.append(Paragraph("Step 6: The PDF Is Built", styles['SectionHead']))
    s.append(Paragraph(
        "When you click \"Export PDF\" on the book page, the system assembles everything into "
        "a professional, print-ready PDF. The book follows a standard 6&times;9 inch trim size "
        "(the most common size for memoir-style books on Amazon KDP, Lulu, and IngramSpark). "
        "Here is what the PDF includes, in order:",
        styles['GuideBody'],
    ))
    s.append(Paragraph("&bull; <b>Title Page</b> &mdash; Book title, subtitle, and \"As told by [your name]\"", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Copyright Page</b> &mdash; Standard copyright notice and Polly Connect credit", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Dedication</b> (optional) &mdash; A personal dedication if you write one", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Table of Contents</b> &mdash; Lists all chapters", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Chapters</b> &mdash; Each chapter with its heading, life phase label, body text, "
        "photos, and QR codes", styles['GuideBullet']))
    s.append(Paragraph("&bull; <b>Back Matter</b> &mdash; A closing message", styles['GuideBullet']))

    s.append(PageBreak())

    # Step 7
    s.append(Paragraph("Step 7: Print and Share", styles['SectionHead']))
    s.append(Paragraph(
        "The PDF is ready to upload directly to a print-on-demand service like Amazon KDP "
        "or Lulu. You can order physical copies for family members. You can also simply share "
        "the PDF digitally &mdash; the QR codes work on screen too.",
        styles['GuideBody'],
    ))

    # How it all connects
    s.append(Paragraph("How It All Connects", styles['SectionHead']))
    s.append(Paragraph(
        "Here is the simple chain from your voice to the printed page:",
        styles['GuideBody'],
    ))
    s.append(Paragraph("1. You <b>talk to Polly</b> &rarr; voice recorded + transcribed to text", styles['GuideBullet']))
    s.append(Paragraph("2. Text saved as a <b>story</b> &rarr; analyzed into a <b>memory</b> with life phase + arc", styles['GuideBullet']))
    s.append(Paragraph("3. You <b>upload photos</b> &rarr; linked to stories on the web portal", styles['GuideBullet']))
    s.append(Paragraph("4. Memories <b>grouped into chapters</b> automatically by life phase and arc", styles['GuideBullet']))
    s.append(Paragraph("5. AI <b>writes each chapter</b> using only your real stories", styles['GuideBullet']))
    s.append(Paragraph("6. You <b>toggle</b> which photos and QR codes go in the book", styles['GuideBullet']))
    s.append(Paragraph("7. Click <b>Export PDF</b> &rarr; print-ready book with photos and scannable voice QR codes", styles['GuideBullet']))

    # Family involvement
    s.append(Paragraph("Family Can Help", styles['SectionHead']))
    s.append(Paragraph(
        "Family members who log in with an access code can also tell stories, upload photos, "
        "and add members to the family tree. The owner and caretaker have full control over "
        "which stories, photos, and QR codes end up in the final book. Family members can "
        "view the book but cannot change the toggles that control what is printed.",
        styles['GuideBody'],
    ))

    # Closing
    s.append(Spacer(1, 24))
    s.append(Paragraph(
        "That is it &mdash; from a conversation with a parrot-shaped speaker to a real book "
        "on your bookshelf. Every voice matters. Every story deserves to be preserved.",
        styles['GuideBody'],
    ))

    s.append(Paragraph("Polly Connect &mdash; 2026", styles['Footer']))

    doc.build(s)
    return buf.getvalue()


if __name__ == "__main__":
    data = build()
    out = "/tmp/how_the_book_is_made.pdf"
    with open(out, "wb") as f:
        f.write(data)
    print(f"Guide PDF written to {out} ({len(data)} bytes)")
