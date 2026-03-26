#!/usr/bin/env python3
"""Generate a user-friendly multi-device setup guide PDF."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch

output_path = os.path.join(os.path.dirname(__file__), '..', 'Polly_Multi_Device_Guide.pdf')
doc = SimpleDocTemplate(output_path, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch)

styles = getSampleStyleSheet()
title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=22, spaceAfter=12)
heading_style = ParagraphStyle('Heading2', parent=styles['Heading2'], fontSize=14, spaceBefore=16, spaceAfter=6, textColor=HexColor('#047857'))
body_style = ParagraphStyle('Body2', parent=styles['BodyText'], fontSize=11, spaceAfter=4, leading=14)
bullet_style = ParagraphStyle('Bullet2', parent=body_style, leftIndent=20, bulletIndent=8)
note_style = ParagraphStyle('Note2', parent=body_style, fontSize=10, textColor=HexColor('#6b7280'), leftIndent=10)

story = []

story.append(Paragraph("Polly Connect — Multi-Device Guide", title_style))
story.append(Spacer(1, 12))

# Section 1: Setup
story.append(Paragraph("Setting Up a New Polly Device", heading_style))
story.append(Paragraph("1. Power on your new Polly. It will create a WiFi network called <b>Polly-Setup</b>.", body_style))
story.append(Paragraph("2. On your phone, connect to the <b>Polly-Setup</b> WiFi network.", body_style))
story.append(Paragraph("3. A setup page will appear. Enter your <b>home WiFi name</b>, <b>password</b>, and the <b>6-digit claim code</b> from your setup card.", body_style))
story.append(Paragraph("4. Polly will restart, connect to your WiFi, and link to the server.", body_style))
story.append(Paragraph("5. Log in at <b>polly-connect.com</b>. If you see a 'Connect Your Device' prompt, enter the same claim code. If it already shows as claimed, you're all set!", body_style))
story.append(Spacer(1, 8))
story.append(Paragraph("<i>Each device gets its own unique identity. You can name them (Kitchen Polly, Bedroom Polly, etc.) on the Devices page.</i>", note_style))

# Section 2: Per-Device Settings
story.append(Paragraph("Customizing Each Polly", heading_style))
story.append(Paragraph("When you have multiple Pollys, the Settings page shows <b>device tabs</b> so you can customize each one:", body_style))
story.append(Paragraph("<b>Polly Sounds</b> — Different squawk intervals, chatter frequency, and volume per device.", bullet_style))
story.append(Paragraph("<b>Quiet Hours</b> — Bedroom Polly sleeps 9 PM–7 AM, Office Polly sleeps 8 PM–3 AM.", bullet_style))
story.append(Paragraph("<b>Snooze</b> — Snooze one Polly without affecting the others.", bullet_style))
story.append(Paragraph("<b>Kid Mode</b> — Turn on kid-friendly jokes for the kids' room Polly.", bullet_style))
story.append(Paragraph("<b>Reminders</b> — Assign reminders to specific devices. Morning vitamins on Kitchen Polly, bedtime reminder on Bedroom Polly.", bullet_style))
story.append(Spacer(1, 8))
story.append(Paragraph("<i>If you don't customize a device, it inherits the default settings from your account.</i>", note_style))

# Section 3: What's Shared
story.append(Paragraph("What All Your Pollys Share", heading_style))
story.append(Paragraph("All devices on your account share the same:", body_style))
story.append(Paragraph("Stories, photos, and family tree", bullet_style))
story.append(Paragraph("Legacy book and chapters", bullet_style))
story.append(Paragraph("Family message board — leave a message on one, hear it on any", bullet_style))
story.append(Paragraph("Stored items ('Where are my keys?')", bullet_style))
story.append(Paragraph("Blessings and prayer recordings", bullet_style))
story.append(Spacer(1, 8))
story.append(Paragraph("<i>Think of it like having the same parrot in multiple rooms — same personality, same memories, different perch.</i>", note_style))

# Section 4: Tips
story.append(Paragraph("Tips for Multiple Pollys", heading_style))
story.append(Paragraph("<b>Talk to the closest one.</b> Each Polly listens independently. Talk to whichever is nearest.", body_style))
story.append(Paragraph("<b>Two people can talk at the same time</b> — to different Pollys. Each handles its own conversation.", body_style))
story.append(Paragraph("<b>Messages sync instantly.</b> Leave a message at work, your family hears 'Message! Message!' at home.", body_style))
story.append(Paragraph("<b>Snooze is per-device.</b> Snooze the bedroom Polly for nap time without silencing the kitchen one.", body_style))
story.append(Paragraph("<b>Reminders are flexible.</b> Your 4 AM vitamins can go to just your device — your partner's Polly stays quiet.", body_style))
story.append(Spacer(1, 20))

story.append(Paragraph("polly-connect.com", ParagraphStyle('Footer', parent=body_style, fontSize=10, textColor=HexColor('#9ca3af'), alignment=1)))

doc.build(story)
print(f"PDF saved to: {output_path}")
