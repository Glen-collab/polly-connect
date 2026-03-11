#!/usr/bin/env python3
"""Generate 50 stories for Gi Lee demo tenant - all spoken in first person as if told to Polly."""
import sqlite3
import json

DB_PATH = "polly.db"

# Each story: (speaker_name, transcript, chapter/theme, tags)
# Tags format: [(type, value), ...]

STORIES = [
    # ═══════════════════════════════════════════════════
    # THEME 1: family_kitchen / ordinary_world / childhood
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "Every morning before school, my grandmother would already be in the kitchen. The whole apartment smelled like congee, that rice porridge she made with dried scallops and ginger. I would sit on the wooden stool by the counter and she would hand me a bowl without saying a word. Just a nod. That was her love language, feeding people. The kitchen was tiny, smaller than most bathrooms, but she moved through it like a dancer. Every jar had its place. Every spice was within reach. I can still hear the click of the gas stove and the sound of her cleaver hitting the cutting board. That rhythm was the heartbeat of our house.",
     "family_kitchen",
     [("person", "Mei-Hua Lee"), ("place", "Chinatown"), ("place", "San Francisco"), ("year", "1965")]),

    ("Mei-Hua Lee",
     "In our kitchen, nothing was wasted. The bones from last night became this morning's broth. Vegetable scraps went into the compost for the rooftop garden. I learned this from my own mother in Hong Kong. When you grow up with very little, you learn that everything has a second life. Gi used to watch me roll dumplings and he would try with his little fingers. They were lumpy and ugly but I cooked them anyway and told him they were the best ones. He believed me every time. That boy had such serious eyes, even at five years old. Like he was studying the world.",
     "family_kitchen",
     [("person", "Gi Lee"), ("person", "Mei-Hua Lee"), ("place", "Chinatown"), ("year", "1963")]),

    ("Lian Lee",
     "My sewing room was right next to the kitchen, so I could hear everything. The radio played Cantonese opera all day while I worked the machine. Gi would come home from school and sit on the floor surrounded by fabric scraps, building little forts and bridges out of them. He never complained about the noise. I think the rhythm of the sewing machine calmed him the same way it calmed me. Sometimes he would bring his homework in there just to be near me. He did not need to talk. He just wanted to be in the same room. That is how I knew he was like his grandfather. Quiet on the outside, a whole world spinning on the inside.",
     "family_kitchen",
     [("person", "Lian Lee"), ("person", "Gi Lee"), ("place", "Grant Avenue"), ("place", "San Francisco"), ("year", "1968")]),

    ("Gi Lee",
     "My father worked on cars the way some men pray. With total focus. His hands were always stained with grease, and he had this way of squinting at an engine like he was reading its mind. I was the flashlight holder. That was my job. And if I moved the beam even a little, he would snap at me. Hold it steady. Right there. I hated it at the time. I wanted to be outside playing with Tommy. But looking back, those hours in the garage taught me something I use every day in the dojo. Patience. Precision. The understanding that if you cannot hold still and focus on one small thing, you will never master anything big.",
     "family_kitchen",
     [("person", "James Lee"), ("person", "Gi Lee"), ("person", "Tommy Lee"), ("place", "San Francisco"), ("year", "1970")]),

    ("Gi Lee",
     "Saturday mornings, Grandfather Wei would wake me before the sun came up. No alarm, just his hand on my shoulder. We would walk to Portsmouth Square in the dark, the fog so thick you could taste the salt. He would begin his tai chi and I would copy him, this little kid stumbling through the forms while old men smoked cigarettes on the benches and watched. Nobody laughed. In Chinatown, a grandfather teaching his grandson was sacred. Those mornings are the reason I still train at four AM. Not because anyone makes me. Because that quiet before the world wakes up, that is when you find out who you really are.",
     "family_kitchen",
     [("person", "Wei Lee"), ("person", "Gi Lee"), ("place", "Portsmouth Square"), ("place", "Chinatown"), ("year", "1966")]),

    ("Sarah Chen",
     "The first time Gi cooked for me, he made his grandmother's congee recipe. He was so focused, stirring that pot like it was a meditation. He told me his grandmother never wrote anything down, she just knew. So he was going from memory, tasting and adjusting. It was not perfect, he admitted that. But there was something in the way he stood over that stove. I could see the little boy in Chinatown standing next to his grandmother. That is when I knew this man had depth that most people would never see. The kitchen was where he let his guard down.",
     "family_kitchen",
     [("person", "Sarah Chen"), ("person", "Gi Lee"), ("person", "Mei-Hua Lee"), ("place", "Portland"), ("year", "1985")]),

    ("Gi Lee",
     "Grandmother had this thing she did every Chinese New Year. She would make jiaozi, hundreds of them, and she would hide a coin inside one dumpling. Whoever found the coin would have good luck all year. I found it three years in a row and I thought I was the luckiest kid alive. It was not until I was grown that my mother told me Grandmother always put the coin in the one she handed directly to me. She cheated for me every single year. I still make those dumplings with Lily and the boys. I have never told them about the coin trick. But Lily always seems to find it.",
     "family_kitchen",
     [("person", "Mei-Hua Lee"), ("person", "Lian Lee"), ("person", "Lily Lee"), ("place", "Chinatown"), ("year", "1968")]),

    # ═══════════════════════════════════════════════════
    # THEME 2: family_characters / ordinary_world / childhood
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "Uncle David was the only person in our family who had been to Japan. This was the nineteen sixties, and for a Chinese American man to go study judo in Tokyo was unheard of. My father thought he was crazy. My grandfather said nothing, which in our family meant he approved. David would come to family dinners and tell stories about training in freezing dojos, sleeping on tatami mats, getting thrown by men half his size. I hung on every word. He was the one who told me that martial arts was not about fighting. It is about becoming someone worth being. That sentence changed my entire life.",
     "family_characters",
     [("person", "David Lee"), ("person", "James Lee"), ("person", "Wei Lee"), ("place", "San Francisco"), ("year", "1967")]),

    ("Tommy Lee",
     "Gi and I were born three weeks apart and our mothers joked that we were twins separated at birth. We did everything together. Racing bikes through Chinatown, jumping off the loading dock behind the fish market, sparring in my dad's garage with these ridiculous homemade padding we made from couch cushions and duct tape. Gi was always more serious than me. I wanted to have fun. He wanted to be great. Even at twelve he had this intensity that was almost scary. I became a lawyer. He opened a dojo. But every time we spar on Saturdays, we are twelve years old again.",
     "family_characters",
     [("person", "Gi Lee"), ("person", "Tommy Lee"), ("place", "Chinatown"), ("place", "San Francisco"), ("year", "1970")]),

    ("Gi Lee",
     "My grandmother believed in herbal medicine the way Americans believe in aspirin. She had a remedy for everything. Stomach ache? Ginger and chrysanthemum tea. Cannot sleep? Dried longan and jujube. She would brew these teas that smelled like a forest floor and make us drink every drop. I complained every time. But I also never got seriously sick as a kid. When I tore my knee years later and the doctors wanted surgery, the first thing I thought of was Grandmother and her teas. Not because herbs could fix a torn ligament. But because she taught me that healing starts with believing you can heal.",
     "family_characters",
     [("person", "Mei-Hua Lee"), ("person", "Gi Lee"), ("place", "Chinatown"), ("year", "1970")]),

    ("Lian Lee",
     "My husband Jin was not a man of many words. He showed love through doing. If the car made a strange noise, he fixed it before I even mentioned it. If a shelf was loose, it was repaired by morning. When Gi told him he wanted to study martial arts instead of going to trade school, Jin did not say anything for three days. I thought he was angry. Then on the fourth day, he drove Gi to Master Chen's dojo and sat in the car for two hours waiting for the class to end. He never said I support you. He just showed up. Every week. For six years.",
     "family_characters",
     [("person", "James Lee"), ("person", "Gi Lee"), ("person", "Master Chen Wei-Ming"), ("place", "San Francisco"), ("year", "1970")]),

    ("Gi Lee",
     "Grandfather's restaurant, the Golden Crane, was more than a restaurant. It was a community center, a counseling office, a place where old men played mahjong and argued about politics. Grandfather knew every customer by name. He would sit at the corner table after the lunch rush and just watch. I asked him once what he was looking at. He said I am reading the room the way you read a book. Every person who walks through that door has a story. Your job is to pay attention. I use that same lesson in the dojo. When a new student walks in, I do not look at their body. I read their eyes.",
     "family_characters",
     [("person", "Wei Lee"), ("person", "Gi Lee"), ("place", "Golden Crane"), ("place", "Chinatown"), ("year", "1972")]),

    ("Wei Lee",
     "When I came to America, I had seventeen dollars and a name nobody could pronounce. The first ten years I washed other people's clothes. My hands cracked from the lye soap every winter. But I saved every penny. When I finally opened the Golden Crane, I put a sign in the window that said Everyone Welcome. Some of the old-timers in Chinatown said I was foolish. Chinese restaurant for Chinese people, they said. But I remembered being the outsider. I remembered what it felt like when nobody would serve you. My restaurant would be different. And it was. For forty-two years, it was different.",
     "family_characters",
     [("person", "Wei Lee"), ("place", "Golden Crane"), ("place", "Chinatown"), ("place", "San Francisco"), ("year", "1928")]),

    ("Gi Lee",
     "Aunt Rose was the peacemaker. Whenever my father and Uncle David got into it about politics or money or whose kid was doing better in school, Rose would appear with a plate of almond cookies and change the subject so smoothly you did not even realize what happened. She taught third grade for thirty-five years and I think she used those same skills on our family that she used on eight-year-olds. Distract, redirect, offer a treat. It worked every time. She always had butterscotch candy in her purse and she would slip one to me and Tommy when the adults were not looking. I still keep butterscotch in my desk drawer at the dojo because of her.",
     "family_characters",
     [("person", "Rose Lee"), ("person", "David Lee"), ("person", "James Lee"), ("person", "Tommy Lee"), ("place", "San Francisco"), ("year", "1972")]),

    # ═══════════════════════════════════════════════════
    # THEME 3: holidays / ordinary_world / childhood
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "Chinese New Year in Chinatown was the biggest event of the year. The lion dancers would come through Grant Avenue and the drums were so loud you felt them in your chest. Grandfather would give us red envelopes with crisp dollar bills inside. Not much, maybe two or three dollars, but it felt like a fortune. The firecrackers terrified me when I was small. I would press my hands over my ears and squeeze my eyes shut. My father picked me up and said the noise chases away evil spirits. After that, every explosion sounded like protection instead of danger. That is what a father does. He reframes the fear.",
     "holidays",
     [("person", "Wei Lee"), ("person", "James Lee"), ("person", "Gi Lee"), ("place", "Grant Avenue"), ("place", "Chinatown"), ("year", "1964")]),

    ("Mei-Hua Lee",
     "Every Moon Festival I would make mooncakes from scratch. It took two full days. The children did not appreciate the work, they just wanted to eat them. But the making was the point. I would press the molds and think about my mother doing the same thing in Hong Kong, and her mother before her. When I pressed a mooncake into shape, I was pressing four generations of women into that pastry. Gi was the only grandchild who sat and watched the whole process without getting bored. He understood that the slow work is the important work. I think that is why he became who he became.",
     "holidays",
     [("person", "Mei-Hua Lee"), ("person", "Gi Lee"), ("place", "Chinatown"), ("place", "San Francisco"), ("year", "1966")]),

    ("Gi Lee",
     "Christmas was interesting in our house because we were not a Christian family but we lived in America. So we had this hybrid thing. Grandmother would make Chinese dishes and my mother would put up a small tree with paper ornaments she sewed herself. No presents under the tree, that was not our tradition. But my parents always took us to see the window displays downtown. Union Square all lit up. I remember holding my mother's hand and staring at these elaborate scenes behind the glass. She told me Americans are good at making things look beautiful on the outside. We are good at making things beautiful on the inside. Both matter.",
     "holidays",
     [("person", "Lian Lee"), ("person", "Gi Lee"), ("place", "Union Square"), ("place", "San Francisco"), ("year", "1966")]),

    ("Sarah Chen",
     "Our family Thanksgiving is legendary. Gi insists on making his grandmother's dumplings alongside the turkey. Tom brings his tri-tip. The kids argue about music. Lily tries to get everyone to do a group stretch which nobody wants to do. Marcus once brought his guitar and played jazz while we ate and Gi pretended not to love it but I could see him tapping his foot under the table. It is chaos and noise and it is perfect. After dinner, Gi always steps outside alone for a few minutes. He told me once that he is saying thank you to the people who cannot be at the table anymore.",
     "holidays",
     [("person", "Gi Lee"), ("person", "Tom Chen"), ("person", "Lily Lee"), ("person", "Marcus Lee"), ("place", "Portland"), ("year", "2020")]),

    ("Gi Lee",
     "Every summer, my parents would take us to Stinson Beach. Just a day trip, we could not afford vacations. My father would sit in a folding chair and read the newspaper while my mother unpacked enough food for ten people even though there were only four of us. Tommy would come sometimes and we would build these elaborate sand structures and then practice our kicks by destroying them. My father would look over his newspaper and shake his head. Two perfectly good boys wasting energy on nonsense. But he was smiling when he said it. Those beach days were the only times I saw my father fully relax.",
     "holidays",
     [("person", "James Lee"), ("person", "Lian Lee"), ("person", "Tommy Lee"), ("person", "Gi Lee"), ("place", "Stinson Beach"), ("year", "1969")]),

    # ═══════════════════════════════════════════════════
    # THEME 4: growing_up_work / call_to_adventure / adolescence
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "My first day at Master Chen's dojo I was twelve years old and thought I was tough because I had been doing tai chi with my grandfather for years. Master Chen told me to stand in horse stance. Just stand there. I lasted maybe four minutes before my legs were shaking so bad I fell over. The other students did not laugh. Master Chen just looked at me and said good. Now you know where you begin. I trained with him for the next eighteen years. That first lesson never left me. You cannot grow until you are honest about where you are. Every new student at my dojo, the first thing I do is show them where they begin.",
     "growing_up_work",
     [("person", "Master Chen Wei-Ming"), ("person", "Gi Lee"), ("place", "San Francisco"), ("year", "1970")]),

    ("Gi Lee",
     "After school I worked at Grandfather's restaurant. Washing dishes mostly. The water was so hot it turned my hands red and the pots were enormous. I would stand on a milk crate to reach the sink. Grandfather paid me two dollars a day. Not because he was cheap, he just believed you should earn your way into better work. After six months of dishes, he moved me to prep. After a year, I was helping cook. He was teaching me the same thing Master Chen taught me. Start at the bottom. Respect the process. The ones who skip ahead are the ones who never truly learn.",
     "growing_up_work",
     [("person", "Wei Lee"), ("person", "Gi Lee"), ("place", "Golden Crane"), ("place", "Chinatown"), ("year", "1971")]),

    ("Ray Tanaka",
     "I met Gi at a junior tournament in Oakland when we were sixteen. I was from San Jose, he was from the city. We were in different weight classes so we never fought each other, but I watched him spar and I knew immediately this guy was different. Most kids at that age are all aggression, no thought. Gi moved like he was solving a math problem. Calm, precise, efficient. After the tournament I walked up and said I have never seen anyone fight like you. He said I do not fight. I solve problems. We have been best friends for forty-nine years since that conversation.",
     "growing_up_work",
     [("person", "Ray Tanaka"), ("person", "Gi Lee"), ("place", "Oakland"), ("year", "1974")]),

    ("Gi Lee",
     "The moment I decided martial arts was my life happened when I was seventeen. I had just won the Northern California junior championship and my father took me out for noodles afterward. He was quiet for a long time and then he said I do not understand what you do. But I see that it makes you someone. That was the closest my father ever came to saying he was proud of me. I went home and sat on my bed and something clicked. This was not a hobby. This was not something I did. This was who I was. The next morning I was at the dojo before Master Chen arrived. He saw me waiting at the door and just nodded. He already knew.",
     "growing_up_work",
     [("person", "Gi Lee"), ("person", "James Lee"), ("person", "Master Chen Wei-Ming"), ("place", "San Francisco"), ("year", "1975")]),

    ("Gi Lee",
     "Master Chen had a rule. Before you could learn any technique, you had to sweep the dojo floor. Every day. Even the advanced students swept. I asked him once why a black belt still sweeps floors. He said the floor does not care what color your belt is. Dirt is dirt. If you think you are above the small tasks, you have already lost. I never forgot that. At Pacific Way, everyone sweeps. Even me. Especially me. My students need to see that I am not above the work. The day you stop sweeping is the day you stop learning.",
     "growing_up_work",
     [("person", "Master Chen Wei-Ming"), ("person", "Gi Lee"), ("place", "San Francisco"), ("year", "1972")]),

    ("Gi Lee",
     "When I told my father I was not going to trade school, that I wanted to teach martial arts, he did not yell. He just got very quiet, which was worse. My mother told me later that he sat in the garage for two hours that night, not working on anything, just sitting. He was afraid for me. He had worked with his hands his whole life so his children would not have to. And here I was, choosing to work with my hands in a completely different way. It took him years to understand. But he drove me to Master Chen every week. He showed up. That was his version of I believe in you.",
     "growing_up_work",
     [("person", "Gi Lee"), ("person", "James Lee"), ("person", "Lian Lee"), ("person", "Master Chen Wei-Ming"), ("place", "San Francisco"), ("year", "1976")]),

    ("Lian Lee",
     "When Gi was fifteen, he came home from the dojo with a black eye and a split lip. I was furious. I wanted to march down to that school and give that teacher a piece of my mind. But Gi stopped me. He said Mama, I earned this. The boy who hit me was better than me today. Tomorrow I will be better than him. I stood there in my kitchen looking at my son with blood on his face, smiling, and I thought this child is nothing like his father or me. He came from somewhere else entirely. Maybe he came from those mornings with Wei in the park. Maybe discipline skips a generation and lands harder.",
     "growing_up_work",
     [("person", "Lian Lee"), ("person", "Gi Lee"), ("person", "Wei Lee"), ("place", "San Francisco"), ("year", "1973")]),

    # ═══════════════════════════════════════════════════
    # THEME 5: courtship / crossing_threshold / young_adult
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "I met Sarah at a tournament in Portland in nineteen eighty-four. She was there with her brother Tom who was competing. I noticed her because while everyone else was watching the fights, she was reading a book. A novel, right there in the bleachers with all that noise. I walked over during a break and asked what she was reading. She looked up and said something worth more than what is happening out there. I should have been offended since I had just won my division. Instead I laughed. Nobody had ever talked to me like that. I asked her to coffee and she said only if you promise not to talk about fighting. I have kept that promise for forty-one years.",
     "courtship",
     [("person", "Sarah Chen"), ("person", "Gi Lee"), ("person", "Tom Chen"), ("place", "Portland"), ("year", "1984")]),

    ("Sarah Chen",
     "The first time Gi met my parents, he brought flowers for my mother and a bottle of plum wine for my father. Very proper. Very traditional. Then my father asked him what he did for a living and Gi said I teach people how to fight. The table went silent. My mother looked like she might faint. But then Gi added, mostly I teach them how not to. That was the moment my father decided he liked this man. Gi has that ability. He can take a room that is tense and turn it warm with one sentence. He does not do it to be clever. He does it because he sees what people need to hear.",
     "courtship",
     [("person", "Sarah Chen"), ("person", "Gi Lee"), ("place", "Portland"), ("year", "1984")]),

    ("Gi Lee",
     "Moving to Portland was the hardest thing I had ever done. I was twenty-seven, leaving San Francisco, leaving Chinatown, leaving my parents, leaving Master Chen, leaving everything I knew. My mother cried. My father shook my hand, which was as emotional as he got. Grandfather was gone by then, passed in eighty-two. I stood on the sidewalk outside our apartment with two suitcases and a bag of training equipment and I thought maybe I should stay. Then I heard Grandfather's voice in my head as clear as if he were standing next to me. The bamboo that does not bend will break. Portland was my bending. It was the best decision I ever made.",
     "courtship",
     [("person", "Gi Lee"), ("person", "Lian Lee"), ("person", "James Lee"), ("person", "Wei Lee"), ("place", "Portland"), ("place", "San Francisco"), ("year", "1985")]),

    ("Gi Lee",
     "I proposed to Sarah on the Hawthorne Bridge at sunset. It was nineteen eighty-five and I had been in Portland for six months. I had no money, no dojo yet, just a rented room and a bag of equipment. I asked her father's permission first because that was how I was raised. Tom told me his father said as long as he treats her like she is the most important person in the room, which he does, then yes. I got down on one knee on that bridge with the Willamette River below us and the sun going down behind Mount Hood and I said I cannot promise you an easy life but I can promise you an honest one. She said that is exactly what I want.",
     "courtship",
     [("person", "Gi Lee"), ("person", "Sarah Chen"), ("person", "Tom Chen"), ("place", "Hawthorne Bridge"), ("place", "Portland"), ("year", "1985")]),

    ("Gi Lee",
     "Opening Pacific Way Dojo in nineteen eighty-six was terrifying. I rented a space in an old warehouse on Division Street. The floor was concrete. I sanded it myself and laid mats that I bought used from a gym that was closing down. The first month, nobody came. Not a single student. I trained alone every morning at four AM and then sat at the front desk until nine PM waiting for someone to walk through the door. Sarah never once suggested I quit. She would bring me lunch and grade papers at the desk while I taught an empty room. The dojo smelled like sawdust and determination. Mike Santos walked in on day thirty-one. He was my first student and he changed everything.",
     "courtship",
     [("person", "Gi Lee"), ("person", "Sarah Chen"), ("person", "Mike Santos"), ("place", "Division Street"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1986")]),

    ("Mike Santos",
     "I was sixteen and angry at the world when I walked into Pacific Way Dojo. My guidance counselor said I needed an outlet or I was going to end up in real trouble. Gi was the only person in the room and I remember thinking this place is empty, this guy must be terrible. He looked at me and said what are you angry about. I said everything. He said good. Anger means you care about something. Now let us figure out what that something is. Nobody had ever said that to me before. Everyone told me to calm down. Gi told me to aim. That is a very different thing.",
     "courtship",
     [("person", "Mike Santos"), ("person", "Gi Lee"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1986")]),

    # ═══════════════════════════════════════════════════
    # THEME 6: raising_kids / trials_allies_enemies / adult
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "Lily was five years old the first time she stepped on the dojo mat. She was tiny and fierce and she already had this look in her eyes that I recognized because I see it in the mirror every morning. She took to it immediately. Natural balance. Natural focus. Sarah was worried it was too aggressive for a little girl but Lily corrected her. Mama, I am not fighting. I am dancing. She still says that. She teaches the kids classes now at Pacific Way and she is better with children than I ever was. She has Sarah's patience blended with my intensity. It is the perfect combination for teaching.",
     "raising_kids",
     [("person", "Lily Lee"), ("person", "Gi Lee"), ("person", "Sarah Chen"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1993")]),

    ("Gi Lee",
     "When Marcus told me he wanted to play guitar instead of training, I will not pretend I handled it well. I was disappointed. I had two sons and I imagined them both at the dojo, carrying on what I had built. Daniel was interested in the physical side, the rehab and recovery. But Marcus wanted music. We argued about it. More than once. Sarah told me I was being exactly like my father, trying to force my path onto my children. That hit me hard because she was right. My father did not understand martial arts. I did not understand jazz. But just like my father, I showed up. I went to every performance. Even the bad ones. Especially the bad ones.",
     "raising_kids",
     [("person", "Marcus Lee"), ("person", "Gi Lee"), ("person", "Sarah Chen"), ("person", "Daniel Lee"), ("person", "James Lee"), ("place", "Portland"), ("year", "2007")]),

    ("Sarah Chen",
     "The twins nearly broke us. Marcus and Daniel arrived three weeks early and suddenly we had a toddler and two newborns. Gi was teaching classes during the day and up with the babies at night. I was recovering from a difficult delivery and could barely walk for the first two weeks. There was one night around three AM, both twins screaming, Lily crying because they woke her up, and I looked at Gi standing in the hallway holding a baby in each arm with this expression of complete calm on his face. He said to me this is just another form. Learn the form. The chaos becomes order. I wanted to throw something at him. But he was right.",
     "raising_kids",
     [("person", "Sarah Chen"), ("person", "Gi Lee"), ("person", "Marcus Lee"), ("person", "Daniel Lee"), ("person", "Lily Lee"), ("place", "Portland"), ("year", "1991")]),

    ("Lily Lee",
     "Growing up in a dojo was weird and wonderful. My friends had normal dads who watched football on Sundays. My dad was teaching roundhouse kicks at six AM and quoting ancient philosophers over dinner. I thought everyone's dad could do a spinning heel kick until I was about eight. When I started bringing friends over, they were terrified of him. He is six feet tall and does not smile much. But then they would see him with the little kids in class, so gentle and patient, and they would relax. My dad has two modes: warrior and teddy bear. There is no in between.",
     "raising_kids",
     [("person", "Lily Lee"), ("person", "Gi Lee"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1996")]),

    ("Gi Lee",
     "The hardest lesson of fatherhood was learning that my children are not extensions of me. They are their own people. Lily chose the dojo but she teaches differently than I do. Marcus chose music and he is brilliant at it. Daniel chose healing. Three children, three completely different paths, and I am proud of all of them. But it took me years to get there. I spent too long trying to mold them into what I wanted instead of watering what was already growing. Master Chen told me once that the best teacher does not create copies. The best teacher creates originals. I finally understand what he meant.",
     "raising_kids",
     [("person", "Gi Lee"), ("person", "Lily Lee"), ("person", "Marcus Lee"), ("person", "Daniel Lee"), ("person", "Master Chen Wei-Ming"), ("place", "Portland"), ("year", "2015")]),

    ("Marcus Lee",
     "Dad never said he was sorry about pushing martial arts on me. That is not how he operates. But one Christmas he gave me a vintage Gibson hollow-body guitar that must have cost him a fortune. Inside the case was a note that said every discipline is the same discipline. Your music is your dojo. I cried. I am not ashamed to say it. That was my father telling me he finally understood. I keep that note in my guitar case and I read it before every performance. It is the best thing he has ever given me.",
     "raising_kids",
     [("person", "Marcus Lee"), ("person", "Gi Lee"), ("place", "Portland"), ("year", "2014")]),

    ("Gi Lee",
     "There was a rival dojo that opened two blocks from Pacific Way in ninety-eight. The owner was a former student of mine who left after a disagreement about teaching methods. He undercut my prices and put up flyers calling his school modern and progressive, implying mine was outdated. I lost eight students in the first month. Sarah found me at four AM hitting the heavy bag so hard my knuckles were bleeding. She did not say anything. She just wrapped my hands and sat with me until the sun came up. I wanted to fight back. She taught me to outlast. Twelve years later, that school closed. Pacific Way is still here.",
     "raising_kids",
     [("person", "Gi Lee"), ("person", "Sarah Chen"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1998")]),

    # ═══════════════════════════════════════════════════
    # THEME 7: neighborhood / ordinary_world / childhood
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "Chinatown in the nineteen sixties was a world within a world. You could walk three blocks in any direction and hear five different dialects. The fish market on Stockton Street smelled so strong it hit you from a block away. The herbalist next door had jars of things I could not identify and did not want to. The bakery made egg tarts that were still warm when you got them. I knew every shopkeeper by name and they knew me. If I did something wrong three blocks from home, my mother would know about it before I got back. There were no secrets in Chinatown. The neighborhood raised you whether you liked it or not.",
     "neighborhood",
     [("person", "Gi Lee"), ("place", "Chinatown"), ("place", "Stockton Street"), ("place", "San Francisco"), ("year", "1966")]),

    ("Gi Lee",
     "When we moved to Portland, I was shocked by how much space there was. In Chinatown, everyone was on top of each other. Our apartment was above the tailor shop and next to a noodle house. In Portland, we had a yard. An actual yard with grass. Our neighbor Mrs. Patterson was this elderly woman who lived alone and I started helping her with groceries every Thursday because she reminded me of my grandmother. Same quiet strength. Same way of looking at you like she already knew what you were going to say. She came to the dojo once, just to watch, and she told me afterward you are doing exactly what you are supposed to be doing. She died in twenty-eighteen at ninety-four. I still miss her.",
     "neighborhood",
     [("person", "Gi Lee"), ("person", "Mrs. Dorothy Patterson"), ("place", "Portland"), ("place", "Chinatown"), ("year", "1986")]),

    ("Tommy Lee",
     "The alley behind the Golden Crane was our playground. It was not much, just a narrow strip of concrete between the restaurant and the dry cleaner. But to us it was a stadium. We would set up crates as obstacles and chase each other doing the worst martial arts you have ever seen. We broke a window once and Grandfather made us sweep the restaurant every day for a month. No pay. That was his punishment, not anger, just consequences and work. I learned more about accountability in that alley than I did in law school. Gi would say we learned more about life in that alley than anywhere else. He is probably right.",
     "neighborhood",
     [("person", "Tommy Lee"), ("person", "Gi Lee"), ("person", "Wei Lee"), ("place", "Golden Crane"), ("place", "Chinatown"), ("year", "1970")]),

    ("Gi Lee",
     "There was an old man in our neighborhood who practiced calligraphy in the park every afternoon. No one knew his real name, everyone just called him Mr. Brush. He would lay out rice paper on a stone table and paint characters with water so they would disappear as they dried. I asked him why he painted with water if it just vanished. He said the beauty is in the doing, not the keeping. Everything disappears. The question is whether you were present while it lasted. I think about that every time I teach a class. The form we practice will fade from memory. But the discipline of doing it stays forever.",
     "neighborhood",
     [("person", "Gi Lee"), ("place", "Chinatown"), ("place", "San Francisco"), ("year", "1972")]),

    # ═══════════════════════════════════════════════════
    # THEME 8: faith_and_church / transformation / reflection
    # ═══════════════════════════════════════════════════
    ("Wei Lee",
     "I used to tell Gi about the bamboo. In Hong Kong, my father grew bamboo behind our house. During typhoons, the rigid trees would snap and fall. But the bamboo bent almost to the ground and then stood back up when the wind stopped. My father said that is how you survive. Not by being the strongest. By being the most flexible. When I came to America with nothing, I bent. When they would not hire Chinese men for good jobs, I bent. When I opened the restaurant and people tried to cheat me, I bent. I never broke. And I taught Gi the same thing. The bamboo bends but it does not break. He has that phrase painted on the wall of his school.",
     "faith_and_church",
     [("person", "Wei Lee"), ("person", "Gi Lee"), ("place", "Hong Kong"), ("place", "Chinatown"), ("year", "1975")]),

    ("Gi Lee",
     "The knee injury in ninety-three almost ended everything. I was thirty-five and I tore my ACL during a demonstration. Stupid. Showing off a jumping kick I had done a thousand times, but my landing was off by an inch. One inch. I heard it pop and I knew before I hit the ground that my life had just changed. The doctor said six months minimum, maybe a year. I was back in the dojo in four months. Not fighting. Not kicking. But standing. Breathing. Doing the simplest forms from a chair at first, then with crutches, then on my own. My students watched their teacher rebuild from nothing. That might have been the most important thing I ever taught them.",
     "faith_and_church",
     [("person", "Gi Lee"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "1993")]),

    ("Gi Lee",
     "After the knee, I hurt my hand. A nerve thing from years of heavy bag work. My right hand went partially numb. I could not make a proper fist. For a martial artist, your hands are everything. I was devastated. Sarah suggested I try something gentler while I healed. So I took up calligraphy, remembering Mr. Brush from the park. Holding a brush requires the same focus as holding a stance. The strokes demand the same precision as a technique. I painted every morning for two years and something shifted inside me. I went from being a fighter who used his hands to hurt, to a man who used his hands to create. When the nerve healed, I was a different person. A better one.",
     "faith_and_church",
     [("person", "Gi Lee"), ("person", "Sarah Chen"), ("place", "Portland"), ("year", "1996")]),

    ("Gi Lee",
     "When Master Chen died in two thousand, I flew back to San Francisco and stood in his empty dojo. The mats were gone. The equipment was packed in boxes. But you could still smell the wood polish and the faint trace of sweat that had soaked into the floors over thirty years. I stood in horse stance in the center of that empty room for one hour. Not because anyone was watching. Because he would have wanted me to. I could hear his voice. The form is not something you do. It is who you are. I closed my eyes and I was twelve again, legs shaking, falling over, hearing him say good, now you know where you begin.",
     "faith_and_church",
     [("person", "Gi Lee"), ("person", "Master Chen Wei-Ming"), ("place", "San Francisco"), ("year", "2000")]),

    ("Gi Lee",
     "I do not follow any organized religion. But I believe in something. I believe in the practice. Every morning at four AM, I go to the dojo and I run through the forms. The same forms Master Chen taught me. The same forms his teacher taught him. The same movements that go back hundreds of years through an unbroken chain of teachers and students. When I move through those forms in the dark before anyone else is awake, I am not alone. I am connected to every person who has ever stood in a dojo and decided to show up when it would have been easier to stay in bed. That is my church. That is my prayer.",
     "faith_and_church",
     [("person", "Gi Lee"), ("person", "Master Chen Wei-Ming"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "2025")]),

    # ═══════════════════════════════════════════════════
    # THEME 9: music_and_fun / ordinary_world / childhood
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "On quiet evenings, my grandmother would take out her erhu, that two-stringed Chinese violin, and play these haunting melodies that came from somewhere deep in her memory. She never told us the names of the songs. I think some of them she made up. The sound would drift through the apartment and everything would stop. My father would put down his newspaper. My mother would stop sewing. Even Tommy if he was there would go completely still. That sound was the voice of a country we had never been to but somehow missed. When she played, we were all in Hong Kong for a few minutes.",
     "music_and_fun",
     [("person", "Mei-Hua Lee"), ("person", "Gi Lee"), ("person", "James Lee"), ("person", "Lian Lee"), ("person", "Tommy Lee"), ("place", "Chinatown"), ("year", "1968")]),

    ("Gi Lee",
     "Saturday afternoons were Bruce Lee movie time. Uncle David had a VCR before anyone else on the block and he would rent every martial arts film he could find. Tommy and I would sit on the floor with popcorn and watch Enter the Dragon for the hundredth time. Uncle David would pause the tape and break down the techniques. See that. That is wing chun. That is jeet kune do. He turns the waist here. He was our commentator, our professor, our hype man. To this day, whenever Tommy and I get together, one of us will quote a Bruce Lee line and the other one finishes it. Be water, my friend.",
     "music_and_fun",
     [("person", "Gi Lee"), ("person", "David Lee"), ("person", "Tommy Lee"), ("place", "San Francisco"), ("year", "1973")]),

    ("Gi Lee",
     "Marcus's first real jazz performance was at a small club in Portland when he was nineteen. Sarah and I drove down and sat at a tiny table in the back. When he started playing, I did not recognize my own son. His eyes were closed and his fingers moved across those strings with the same precision I use in the dojo. The same focus. The same discipline. Halfway through his set, I turned to Sarah and said I understand now. She squeezed my hand and did not say a word because she had understood all along. Every discipline is the same discipline. The instrument does not matter. The commitment does.",
     "music_and_fun",
     [("person", "Gi Lee"), ("person", "Marcus Lee"), ("person", "Sarah Chen"), ("place", "Portland"), ("year", "2010")]),

    ("Tommy Lee",
     "Gi and I used to sneak into the movie theater on Broadway by going through the emergency exit in the alley. We saw everything. Kung fu movies, westerns, whatever was playing. We got caught exactly once. The manager grabbed us both by our collars and marched us out the front door. Gi's face was so red I thought he might explode. He never broke a rule voluntarily. That was my idea and I had dragged him into it. He did not talk to me for a week after that. A whole week. Then he showed up at my house with two movie tickets he had paid for with his restaurant money. He said if we are going to watch movies, we are going to do it right. That was Gi. Even fun had to have integrity.",
     "music_and_fun",
     [("person", "Tommy Lee"), ("person", "Gi Lee"), ("place", "Broadway"), ("place", "San Francisco"), ("year", "1971")]),

    # ═══════════════════════════════════════════════════
    # THEME 10: lessons_and_wisdom / return_with_knowledge / reflection
    # ═══════════════════════════════════════════════════
    ("Gi Lee",
     "People think discipline is punishment. They hear the word and they think of rules and restrictions and being told what to do. That is not discipline. Discipline is freedom. When I wake at four AM and go to the dojo, I am not punishing myself. I am giving myself the one hour of the day that belongs entirely to me. No students, no family needs, no phone calls. Just the form and my breath. Everything I have accomplished started in those dark quiet hours. The dojo. The family. The teaching. All of it grew from the discipline of showing up before the world asked me to. That is what I tell every new student. Discipline is not what you do. It is who you become.",
     "lessons_and_wisdom",
     [("person", "Gi Lee"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "2025")]),

    ("Gi Lee",
     "Teaching Mike Santos taught me more about myself than all my years of training combined. Here was this angry sixteen-year-old who thought the world owed him something, and I saw myself in him. Not the anger part, I was never an angry kid. But the intensity. The need for something to pour yourself into. I did not teach Mike martial arts. I gave him a container for all that energy. A place where intensity was valued instead of punished. When he opened his own dojo in Seattle twenty years later, he called me and said thank you for seeing me when nobody else did. I had to hang up the phone because I could not speak.",
     "lessons_and_wisdom",
     [("person", "Gi Lee"), ("person", "Mike Santos"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("place", "Seattle"), ("year", "2006")]),

    ("Gi Lee",
     "My grandfather told me something when I was very young that I did not understand until I was very old. He said Gi, the strongest man in the room is not the one who can break things. It is the one who can hold things together. I spent my twenties and thirties trying to be the breaker. The fighter. The champion. I wanted to prove I was strong. It was not until I had a family, a business, students depending on me, that I understood what he meant. Real strength is not explosive. It is structural. It is showing up every day and holding the weight so that others can grow. The dojo is not my monument. It is my offering.",
     "lessons_and_wisdom",
     [("person", "Gi Lee"), ("person", "Wei Lee"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "2020")]),

    ("Gi Lee",
     "If my grandchildren ask me someday what I want them to know, it is this. The world will tell you to be louder, faster, bigger. Ignore that. The world does not need more noise. It needs more people who can be still. Who can sit with discomfort and not run from it. Who can hold a stance when their legs are shaking and their mind is screaming quit. Every meaningful thing in my life came from the willingness to be still when everything inside me wanted to move. Grandfather knew this. Master Chen knew this. I learned it slow, the way all important things are learned. Be still. Pay attention. Show up. The rest takes care of itself.",
     "lessons_and_wisdom",
     [("person", "Gi Lee"), ("person", "Wei Lee"), ("person", "Master Chen Wei-Ming"), ("place", "Portland"), ("year", "2025")]),

    ("Gi Lee",
     "Forty years of teaching. Thousands of students. Some became instructors, some became accountants, some I never saw again after their first class. But every single one of them taught me something. The nervous kid who could not make eye contact taught me patience. The middle-aged woman starting over after a divorce taught me courage. The elderly man who could barely stand taught me that movement is life itself, no matter how small. I built Pacific Way as a school for students. It turned out to be a school for me. Master Chen was right about everything. The fist reveals the heart. And teaching reveals the teacher.",
     "lessons_and_wisdom",
     [("person", "Gi Lee"), ("person", "Master Chen Wei-Ming"), ("place", "Pacific Way Dojo"), ("place", "Portland"), ("year", "2026")]),

    ("Ray Tanaka",
     "Gi is the most disciplined person I have ever known and I have known him for almost fifty years. But here is what people do not see. Behind that discipline is a man who feels everything deeply. He cried when his grandfather died. He cried when Master Chen died. He cried at Lily's first tournament win and at Marcus's first jazz show. He does not show it to the world but I have seen it. That is why his students love him. Not because he is tough. Because underneath the toughness is someone who cares so much it hurts. The discipline is not armor. It is how he channels the caring into something useful. That is the real lesson of Gi Lee.",
     "lessons_and_wisdom",
     [("person", "Ray Tanaka"), ("person", "Gi Lee"), ("person", "Wei Lee"), ("person", "Master Chen Wei-Ming"), ("person", "Lily Lee"), ("person", "Marcus Lee"), ("place", "Portland"), ("year", "2025")]),

    ("Sarah Chen",
     "After forty-one years of marriage I can tell you exactly who Gi Lee is. He is the man who gets up at four in the morning not because he has to but because it is who he is. He is the man who still sets a place at Thanksgiving for the people who are gone. He is the man who taught a thousand students but still thinks he has more to learn. He is the man who held my hand in the hospital when the twins were born and whispered we can do this even though his eyes said he was terrified. He is not a perfect man. He is a present man. And that is worth more than perfection could ever be.",
     "lessons_and_wisdom",
     [("person", "Sarah Chen"), ("person", "Gi Lee"), ("person", "Marcus Lee"), ("person", "Daniel Lee"), ("place", "Portland"), ("year", "2025")]),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get tenant_id for Gi Lee
    cur.execute("SELECT id FROM tenants WHERE name='The Lee Family'")
    row = cur.fetchone()
    if not row:
        print("ERROR: The Lee Family tenant not found! Run setup_gi_lee.py first.")
        return
    tenant_id = row[0]
    print(f"Using tenant_id={tenant_id}")

    # Get user_profile id
    cur.execute("SELECT id FROM user_profiles WHERE tenant_id=?", (tenant_id,))
    user_id = cur.fetchone()[0]

    story_count = 0
    tag_count = 0

    for speaker, transcript, chapter, tags in STORIES:
        cur.execute("""INSERT INTO stories
            (user_id, transcript, speaker_name, chapter, source, tenant_id, corrected_transcript, verified, qr_in_book)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, transcript, speaker, chapter, "voice", tenant_id, transcript, 1, 1))
        story_id = cur.lastrowid
        story_count += 1

        for tag_type, tag_value in tags:
            cur.execute("""INSERT INTO story_tags (story_id, tag_type, tag_value, tenant_id)
                VALUES (?,?,?,?)""", (story_id, tag_type, tag_value, tenant_id))
            tag_count += 1

    conn.commit()
    conn.close()
    print(f"Created {story_count} stories with {tag_count} tags for tenant {tenant_id}")
    print("Done!")


if __name__ == "__main__":
    main()
