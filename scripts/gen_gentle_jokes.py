"""
Generate data/jokes.json — Polly's REGULAR jokes (clean / gentle, kid & grandkid
safe). Replaces the old auto-generated "extra_gentle" set, which was ~1000 flat
'calming statement' non-jokes (e.g. "Why did the cloud float slowly? It had no
hurry."). These are real wordplay puns that actually land.

The server (core/data_loader.py) flattens every joke into one pool and picks at
random, so structure is just one block. Run: python scripts/gen_gentle_jokes.py
"""
import json, os

JOKES = [
    # — Animals —
    ("Why don't elephants use computers?", "They're afraid of the mouse."),
    ("What do you call a fish wearing a bowtie?", "So-fish-ticated."),
    ("What do you call a dog that does magic?", "A labracadabrador."),
    ("Why don't seagulls fly over the bay?", "Because then they'd be bagels."),
    ("What do you call a pig that does karate?", "A pork chop."),
    ("What do you call a bear with no teeth?", "A gummy bear."),
    ("What do you call a sleeping dinosaur?", "A dino-snore."),
    ("What do you call a cow that plays an instrument?", "A moo-sician."),
    ("Why did the chicken join a band?", "It already had the drumsticks."),
    ("What do you call a duck that gets all A's?", "A wise quacker."),
    ("What do you call an alligator in a vest?", "An investigator."),
    ("What's a frog's favorite drink?", "Croak-a-cola."),
    ("Why are frogs so happy?", "They eat whatever bugs them."),
    ("What do you call a rabbit that tells jokes?", "A funny bunny."),
    ("What do you call a fish with no eyes?", "A fsh."),
    ("Why don't oysters share their pearls?", "Because they're shellfish."),
    ("What do snails use on their shells?", "Snail polish."),
    ("How do bees get to school?", "On the school buzz."),
    ("What do you call a bee that can't make up its mind?", "A maybe."),
    ("What's a cat's favorite color?", "Purr-ple."),
    ("Why did the owl invite all his friends over?", "He didn't want to be owl by himself."),
    ("What do you call a deer with no eyes?", "No idea."),
    ("What do you call a dinosaur with a big vocabulary?", "A thesaurus."),
    ("Why did the cat sit on the computer?", "To keep an eye on the mouse."),
    ("What do you get from a spoiled cow?", "Spoiled milk."),
    ("What's a sheep's favorite karate move?", "The wool-on roundhouse."),
    ("Why did the horse cross the road?", "The chicken needed a day off."),
    ("What do you call a lazy kangaroo?", "A pouch potato."),
    ("Why don't ants get sick?", "They have little anty-bodies."),
    ("What do you call a snake that builds houses?", "A boa constructor."),
    ("Why did the turkey join the band?", "It had the drumsticks too."),
    ("What do you call a penguin in the desert?", "Lost."),
    ("What do you call a crocodile in a sweater vest?", "An in-vest-igator's cousin."),

    # — Food —
    ("Why did the banana go to the doctor?", "It wasn't peeling well."),
    ("What do you call cheese that isn't yours?", "Nacho cheese."),
    ("Why did the tomato turn red?", "It saw the salad dressing."),
    ("What do you call a sad strawberry?", "A blueberry."),
    ("Why did the cookie go to the doctor?", "It was feeling crummy."),
    ("What do you call fake spaghetti?", "An impasta."),
    ("Why did the grape stop in the middle of the road?", "It ran out of juice."),
    ("How do you fix a cracked pumpkin?", "With a pumpkin patch."),
    ("Why did the lettuce win the race?", "It was a-head."),
    ("Why don't eggs tell each other secrets?", "They might crack up."),
    ("What kind of nut never has any money?", "A cashew... wait, a doughnut."),
    ("Why was the cucumber upset?", "It found itself in a pickle."),
    ("What did the grape say when it got stepped on?", "Nothing — it just let out a little wine."),
    ("What's bread's favorite kind of music?", "Loaf songs."),
    ("Why did the orange take a nap?", "It ran out of juice."),
    ("What do you call a peanut in a spacesuit?", "An astro-nut."),
    ("Why did the coffee file a report?", "It got mugged."),
    ("What do you call a dancing dessert?", "A cha-cha pudding."),
    ("How does a cucumber become a pickle?", "It goes through a jarring experience."),
    ("What did the hamburger name its baby?", "Patty."),

    # — School & Math —
    ("Why was the math book sad?", "It had too many problems."),
    ("Why did the student eat his homework?", "The teacher said it was a piece of cake."),
    ("What's a snake's favorite school subject?", "Hiss-tory."),
    ("Why is six afraid of seven?", "Because seven eight nine."),
    ("Why did the clock get sent to the principal?", "It was tocking too much."),
    ("What's a math teacher's favorite season?", "Sum-mer."),
    ("Why did the geometry book look worn out?", "It had too many angles to work out."),
    ("Why did the pencil get an award?", "It was on the write track."),
    ("What do you call a teacher with no eyes?", "A teacher who can't c."),
    ("Why did the kid bring a ladder to school?", "He wanted to go to high school."),
    ("What did the calculator say to the student?", "You can count on me."),

    # — Nature & Weather (real puns this time) —
    ("Why did the scarecrow win an award?", "He was outstanding in his field."),
    ("What did one wall say to the other wall?", "Meet you at the corner."),
    ("How do trees get on the internet?", "They log in."),
    ("What did the tree wear to the pool party?", "Swimming trunks."),
    ("What's a tree's least favorite month?", "Sep-timber."),
    ("What do clouds wear under their clothes?", "Thunderwear."),
    ("Why is grass so dangerous?", "It's full of blades."),
    ("What did the flower say to the bee?", "Quit bugging me, honey."),
    ("What do you call a flower that runs on electricity?", "A power plant."),
    ("What's a rock's favorite kind of music?", "Rock and roll."),
    ("Why did the leaf go to the doctor?", "It was feeling a little green."),
    ("What did the big flower say to the little flower?", "Hey there, bud."),
    ("Why did the sun go to school?", "To get a little brighter."),
    ("What do you call two days of rain in Texas?", "A weekend."),
    ("Why did the mountain feel confident?", "It was a-peak performer."),
    ("What did the ocean say to the shore?", "Nothing, it just waved."),

    # — Music —
    ("What kind of music do balloons hate?", "Pop music."),
    ("Why did the piano get locked out of its house?", "It lost its keys."),
    ("What's a skeleton's favorite instrument?", "The trom-bone."),
    ("What kind of music do mummies love?", "Wrap music."),
    ("Why couldn't the string quartet climb the stairs?", "They were too high-strung."),
    ("Why did the singer bring a ladder?", "To reach the high notes."),
    ("What do you call a musical insect?", "A humbug."),

    # — Sports & Body —
    ("Why did the golfer wear two pairs of pants?", "In case he got a hole in one."),
    ("Why can't your nose be 12 inches long?", "Because then it would be a foot."),
    ("Why did the bicycle fall over?", "It was two-tired."),
    ("Why did the soccer ball quit the team?", "It was tired of being kicked around."),
    ("What do you call a boomerang that won't come back?", "A stick."),
    ("Why are basketball players such messy eaters?", "They're always dribbling."),
    ("What did one eye say to the other eye?", "Between us, something smells."),
    ("Why did the runner bring a pencil?", "To draw a finish line."),
    ("Why was the broom running late?", "It over-swept."),
    ("What did the foot say to the shoe?", "You complete me."),

    # — Objects, Jobs & Tech —
    ("Why did the computer go to the doctor?", "It had a nasty bug."),
    ("What do you call a belt made out of watches?", "A waist of time."),
    ("Why did the painting get arrested?", "It was framed."),
    ("Why did the phone wear glasses?", "It lost all its contacts."),
    ("Why did the calendar look so nervous?", "Its days were numbered."),
    ("Why did all the fans leave the stadium?", "Because it got too hot."),
    ("Why did the candle feel down?", "It was totally burnt out."),
    ("Why did the book join the police force?", "It wanted to go undercover."),
    ("What do you call a bear caught in the rain?", "A drizzly bear."),
    ("What do you call a robot that takes the scenic route?", "R2-detour."),
    ("Why did the lamp go to school?", "To get a little brighter — like the sun."),
    ("Why did the stamp feel stuck?", "It was attached to its work."),
    ("What did the traffic light say to the car?", "Don't look, I'm about to change."),
    ("Why did the picture frame call for help?", "It was hung up on something."),
    ("What do you call a sleepy pencil?", "A doze of lead."),
    ("Why did the smartphone need a nap?", "Its battery was drained."),
    ("Why was the math homework calling a plumber?", "It had too many leaks in its logic."),
    ("What did the left shoe say after a long day?", "I'm beat."),
    ("Why did the clock go on a diet?", "It had too much tick."),
    ("Why did the door go to school?", "It wanted to be a little more a-door-able."),

    # — Classic clean groaners —
    ("What do you call a man with no arms and no legs in a pool?", "Bob."),
    ("What do you call a fish that needs help with vocals?", "Auto-tuna."),
    ("Why did the cookie cry?", "Because its mom was a wafer too long."),
    ("What do you call a dinosaur that crashes his car?", "Tyrannosaurus wrecks."),
    ("Why did the scientist take out his doorbell?", "He wanted to win the no-bell prize."),
    ("What do you call a factory that makes okay products?", "A satis-factory."),
    ("Why did the gym close down?", "It just didn't work out."),
    ("What did the buffalo say to his son when he left?", "Bison."),
    ("What's the best way to watch a fishing show?", "Live stream."),
    ("Why did the bee get married?", "He found his honey."),
    ("What do you call a pile of cats?", "A meow-ntain."),
    ("Why did the cell phone get glasses?", "It lost its contacts... again, with a smile."),
    ("What do you call a dog that can do magic tricks?", "A labracadabrador, of course."),
    ("Why don't scientists trust atoms?", "Because they make up everything."),
    ("What did the zero say to the eight?", "Nice belt."),
    ("Why did the cracker call the doctor?", "It felt crumby and saltine."),
    ("How does the moon cut its hair?", "Eclipse it."),
    ("What did the tin man say when he got run over?", "Curses... and a little oil, please."),
    ("Why did the melon plan a big wedding?", "Because it cantaloupe."),
    ("What do you call a snowman in July?", "A puddle."),
]


def main():
    block = {
        "week": 1,
        "season": "any",
        "mode": "gentle",
        "jokes": [
            {"id": f"g{i:03d}", "setup": s, "punchline": p}
            for i, (s, p) in enumerate(JOKES, 1)
        ],
    }
    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jokes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([block], f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(JOKES)} gentle jokes -> {out_path}")


if __name__ == "__main__":
    main()
