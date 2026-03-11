#!/usr/bin/env python3
"""Set up Gi Lee demo tenant with full family tree."""
import sqlite3
import random
import bcrypt

DB_PATH = "polly.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Create tenant
    family_code = str(random.randint(100000, 999999))
    cur.execute("INSERT INTO tenants (name, family_code) VALUES (?, ?)",
                ("The Lee Family", family_code))
    tenant_id = cur.lastrowid
    print(f"Tenant created: id={tenant_id}")
    print(f"Family access code: {family_code}")

    # 2. Create account
    pw_hash = bcrypt.hashpw(b"Brooklyn9*", bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO accounts (email, password_hash, name, tenant_id, role, is_admin) VALUES (?,?,?,?,?,?)",
        ("wisconsinbarbell@yahoo.com", pw_hash, "Gi Lee", tenant_id, "owner", 0)
    )
    print("Account created: wisconsinbarbell@yahoo.com / Brooklyn9*")

    # 3. Create device
    cur.execute("INSERT INTO devices (device_id, name, tenant_id) VALUES (?,?,?)",
                ("polly-gi-lee", "Gi Lee Polly", tenant_id))
    print("Device created: polly-gi-lee")

    # 4. Create user profile
    cur.execute("""INSERT INTO user_profiles (name, familiar_name, tenant_id, setup_complete,
        location_city, squawk_interval, chatter_interval, quiet_hours_start, quiet_hours_end)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        ("Gi Lee", "Gi", tenant_id, 1, "Portland, OR", 10, 45, 21, 7))
    print("User profile created: Gi Lee")

    # 5. Create family members
    family = [
        ("Wei Lee", "grandfather", "grandfather", -2, 1, "Mei-Hua Chen",
         "Immigrated from Hong Kong in the 1920s. Ran a laundry shop then opened Golden Crane restaurant in San Francisco Chinatown. Did tai chi every morning in Portsmouth Square. Quiet, wise, stoic."),
        ("Mei-Hua Lee", "grandmother", "grandmother", -2, 1, "Wei Lee",
         "Wei's wife. Legendary cook whose dumplings drew people from across Chinatown. Held the family together with herbal remedies, fierce love, and quiet warmth. Played the erhu on quiet evenings."),
        ("James Lee", "father", "father", -1, 1, "Lian Wong",
         "First-generation American, went by Jin at home. Auto mechanic then managed Golden Crane after Wei retired. Practical and hardworking. Showed up to every tournament even though he didn't understand martial arts."),
        ("Lian Lee", "mother", "mother", -1, 1, "James Lee",
         "Born Lian Wong. Seamstress who ran a tailoring shop on Grant Avenue. Gentle but fierce protector of family. Her sewing room hummed with old Cantonese radio dramas."),
        ("David Lee", "uncle", "uncle", -1, 0, "Rose Lee",
         "Jin's younger brother, the family adventurer. Traveled to Japan in the 1960s to study judo. Came back with stories and techniques that lit Gi's martial arts fire."),
        ("Rose Lee", "aunt", "aunt", -1, 0, "David Lee",
         "David's wife. Elementary school teacher for 35 years. Always had butterscotch candy in her purse. The calm center of every family gathering."),
        ("Tommy Lee", "cousin", "cousin", 0, 0, None,
         "David and Rose's son, same age as Gi. Training partner growing up. They raced bikes through Chinatown alleys and sparred in the garage. Eventually became a lawyer but still trains on weekends."),
        ("Sarah Chen", "spouse", "spouse", 0, 0, "Gi Lee",
         "Met Gi at a tournament in Portland, 1984. Elementary school teacher. The grounding force who sees through his tough exterior. Married 1985."),
        ("Lily Lee", "daughter", "daughter", 1, 0, None,
         "Born 1988. A natural in the dojo from age 5. Now teaches kids classes at Pacific Way Dojo. Has her father's intensity and her mother's patience."),
        ("Marcus Lee", "son", "son", 1, 0, None,
         "Born 1991, Daniel's twin. Chose jazz guitar over martial arts. Lives in NYC, plays clubs in the Village. Calls home every Sunday."),
        ("Daniel Lee", "son", "son", 1, 0, None,
         "Born 1991, Marcus's twin. Physical therapist specializing in sports rehab. Inherited the healing side of martial arts."),
        ("Ray Tanaka", "friend", "friend", 0, 0, None,
         "Met Gi at his first tournament at age 16. Lifelong training partner. Owns Tanaka's Ramen in Portland. Still spars with Gi on Saturday mornings."),
        ("Master Chen Wei-Ming", "mentor", "mentor", -1, 1, None,
         "Gi's martial arts teacher from age 12. Strict traditionalist who demanded perfection in form and character. His philosophy: the fist reveals the heart. Passed away 2000."),
        ("Mike Santos", "friend", "friend", 1, 0, None,
         "First student at Pacific Way Dojo in 1986. Started as a troubled teenager, became disciplined, now runs his own dojo in Seattle."),
        ("Mrs. Dorothy Patterson", "friend", "friend", -1, 1, None,
         "Elderly neighbor in Portland who Gi helped with groceries every Thursday. She reminded him of his grandmother. Passed in 2018 at 94."),
        ("Tom Chen", "brother-in-law", "brother-in-law", 0, 0, None,
         "Sarah's brother. Portland firefighter, 30 years on the job. Anchors every family barbecue with terrible jokes and incredible tri-tip."),
    ]

    for name, rel, rto, gen, dec, spouse, bio in family:
        norm = name.lower().strip()
        cur.execute("""INSERT INTO family_members
            (name, name_normalized, relationship, relation_to_owner, generation, deceased, spouse_name, bio, tenant_id, visit_count)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (name, norm, rel, rto, gen, dec, spouse, bio, tenant_id, 5))

    print(f"Created {len(family)} family members")

    conn.commit()
    conn.close()
    print("Infrastructure setup complete!")


if __name__ == "__main__":
    main()
