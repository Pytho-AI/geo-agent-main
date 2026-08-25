# TC 7-100.2 -- Doctrinal Employment Context (for task-organizing templates at ingest)

Sourced verbatim/paraphrased from TC 7-100.2 (Opposing Force Tactics, 9 Dec 2011). Page
refs are doc page numbers (e.g. "2-15"). This file captures HOW the OPFOR task-organizes
and employs forces -- the functional-role vocabulary that should drive how force-template
nodes get labeled/grouped at ingest, not force-structure data itself (that's in the JSONL
chunks).

## Command and support relationships (Table 2-1, p.2-2)

Four relationships, shifting during an operation to align force with task:
- **Constituent**: forces assigned directly to a unit, integral part of it (organic to
  TOE, or attached after formation). Commanded by / logistics from / positioned by /
  priorities from the GAINING unit in all four respects.
- **Dedicated**: identical to constituent except logistics still comes from a PARENT
  headquarters of similar type (example: an attack helicopter company allocated to a BTG
  -- BTG lacks the technical/repair expertise, so logistics stays with the aviation
  parent while the company executes missions exclusively for the BTG). Marked (DED) in
  plans/orders.
- **Supporting**: commanded by and logistics from the PARENT; positioned and prioritized
  by the SUPPORTED headquarters. Lets the supported commander reposition/reprioritize
  rapidly without a permanent command relationship (example: an MRL battalion supporting
  a BTG for one phase, ready to shift to DTG reserve support next phase). Does not have
  to be inside the supported unit's AOR. Marked (SPT).
- **Affiliated**: self-commanded, self-logistics (or from a "parent"), self-positioned;
  priorities by mutual agreement only -- no command relationship exists. Typically
  nonmilitary/paramilitary (criminal cartels, insurgent organizations) operating in a
  unit's AOR that the unit can sufficiently influence to act in concert with it for a
  limited time. Marked (AFL) in rare cases. On org charts, affiliated status = DASHED
  line (not solid) connecting the affiliated force to the unit -- distinct from dashed
  BOXES, which mean "may or may not be present."

## Administrative Force Structure (AFS) vs fighting (task-organized) force structure

Peacetime AFS (para 1-6/1-7, 2-11/2-12) = the aggregate of headquarters/facilities/
installations that man/train/equip forces; groups forces into corps/armies/army groups or
geographic military regions/districts for administrative purposes. AFS TOE structures are
documented in FM/TC 7-100.4. In wartime, administrative commands are force PROVIDERS --
they transfer major forces to task-organized fighting commands (rarely, an admin command
itself becomes a fighting command). The AFS grouping normally DIFFERS from the go-to-war
fighting force structure (TC 7-100.4 explicitly cross-referenced as the source for AFS
TOE and for task-organizing guidance -- TC 7-100.2 does not duplicate it, it lays the
strategic/tactical C2 and task-org framework on top).

## Operational-level hierarchy above tactical (ch1, p.1-8 to 1-10)

Theater (Chief of General Staff serves as theater commander in most campaigns, eliminating
one echelon) -> **Field Group (FG)** (optional; largest operational-level org, formed when
theater span of control exceeds 4-5 subordinate commands, or when a standing OSC
headquarters evolves upward after receiving additional major commands) -> **Operational-
Strategic Command (OSC)** (the OPFOR's PRIMARY operational organization; standing
headquarters with no permanently assigned forces -- receives division/brigade/battalion-
size organizations allocated by the current Strategic Campaign Plan (SCP); when not
executing/training, exists only as a planning HQ) -> tactical level: DTG/division, BTG/
brigade, or separate battalion. Example OSC composition (para 1-18): one or more OSCs
composed of SPF brigade(s) + affiliated guerrilla brigade(s) + INFOWAR battalion(s) +
several affiliated insurgent organizations -- HQ need not be colocated with subordinates,
which may be in a neighboring country while the OSC HQ stays inside State borders.

Types of offensive action recognized AT OSC LEVEL (para 1-56): attack, limited-objective
attack, strike (rapid destruction of a key enemy organization via synergistic massed
precision fires + maneuver). Types of defensive action at OSC level (para 1-57): maneuver
defense, area defense -- same two types re-used at tactical group/division/brigade level
(ch4) and detachment/battalion-and-below level (ch4).

## Tactical-level organization sizing and roles (ch2, p.2-3 to 2-11)

- **Division**: largest tactical formation in the AFS. Can serve as DTG basis; sustains
  independent ops several days; integrates interagency forces up to brigade/group size.
- **Maneuver brigade**: the OPFOR's basic combined-arms unit. "Divisional" if constituent
  to a division, "separate" (marked (Sep)) if designed for independent missions without
  further allocation; a brigade that's part of a division may be marked (Div). Sustains
  independent ops 1-3 days; integrates interagency forces up to battalion size.
- **Tactical group** = a task-organized division or brigade that received additional land
  forces (from MOD, Ministry of Interior, or affiliated forces) to ensure unity of command
  in an AOR. From divisions = **DTG** (division tactical group); from brigades = **BTG**
  (brigade tactical group). A DTG may fight under an OSC or as a separate FG unit; a BTG
  may fight under a division/DTG OR as a separate OSC/FG unit. ANY division or brigade
  receiving additional assets from a higher command becomes a DTG or BTG by definition --
  it normally retains its original constituent assets too, though a higher command can
  also cross-pollinate units between divisions/brigades when forming a tactical group.
- **Battalion**: the OPFOR's basic UNIT OF ACTION. Plans 6-24hr ahead; serves as BDET
  basis; executes basic combat missions as part of a larger force.
- **Company/battery**: the largest OPFOR unit WITHOUT a staff. In fire-support units,
  called a battery. Executes a single tactical task at a time; serves as CDET basis.
- **Platoon**: smallest unit typically expected to conduct independent fire and maneuver.
  Serves as basis for a functional element or patrol; executes a single tactical task;
  can control a small riot/crowd/demonstration.
- **Detachment** (BDET/CDET): smallest COMBINED ARMS formation, task-organized by
  definition, built around a battalion (BDET) or company (CDET) base plus mission-tailored
  augmentation (artillery/mortar, air defense, engineer [obstacle/survivability/mobility],
  heavy weapons [HMG, AGL, ATGM], specialty equipment [flame, specialized recon,
  helicopters], interagency [company-size for BDET, platoon-size for CDET], chemical
  defense, antitank, medical, logistics, signal, EW; BDETs ALSO accept dedicated/
  supporting SPF, aviation (combat/transport helicopter), and UAV units). The basic type
  is the **independent mission detachment (IMD)** -- formed for missions separated in
  space/time from the parent unit: seizing key terrain, linkup with airborne/heliborne
  forces, tactical movement on secondary axes, pursuit/envelopment, raid, ambush. Other
  named detachment types defined in later chapters: counterreconnaissance detachment,
  urban detachment, security detachment (ch5/6), reconnaissance detachment (ch7/8),
  movement support detachment, obstacle detachment (ch12).
- **Integrated Fires Command (IFC)**: standing C2 structure + task-org of constituent/
  dedicated fire-support units. Division/DTG AND ABOVE ONLY (brigades/BTGs and below do
  NOT have an IFC -- they have a "chief of fire support coordination" staff element
  instead, inside the operations section). Exercises C2 of all constituent/dedicated army
  aviation, artillery, missile units at that echelon, plus all allocated RISTA assets.
  Commanded by the division/DTG Deputy Commander from a dedicated IFC CP. Can also be
  given command of maneuver forces (e.g., disruption force, exploitation force) when
  tightly coordinated fires are required.
- **Integrated Support Command (ISC)**: aggregate of combat service support units
  (organic to the division + additional AFS allocations) not suballocated to lower
  echelons. Division/DTG allocates part of its ISC as an **Integrated Support Group
  (ISG)** to support the IFC, remainder as a second ISG supporting the rest of the
  division/DTG. May also include combat-support-task units (chemical, engineer, law
  enforcement). Detail in ch14.

## Functional organization of forces and elements (para 2-49 to 2-58, p.2-15/2-16) -- CORE DOCTRINE

At brigade/BTG and above, functionally-designated subordinates are called **forces**; at
battalion/BDET and below, **elements**. A commander's combat order specifies functional
organization -- what each subordinate DOES, not just its unit designation -- giving a
common, unambiguous language that survives changing unit names/numbers/code words and
adapts on the fly (a unit or part of it can be re-designated mid-fight, e.g. part of a
fixing force reallocated to become part of the exploitation force). Two broad categories:

**Action forces/elements** -- perform the PRIMARY function/task that accomplishes the
mission objective:
- Generic term: *action force* / *action element*.
- Specific designations (assigned by the higher commander, preferred over the generic
  term for clarity): *raiding element* (detachment-level raid), *exploitation force*
  (brigade/BTG and higher offense -- exploits a window of opportunity created by another
  force), *main defense force* / *main defense element* (performs the main defensive
  mission in the battle zone) -- EXCEPT in a **maneuver defense**, where the main
  defensive action is split across two functional forces: the **contact force** and the
  **shielding force** (defined further in ch4).

**Enabling forces/elements** -- everything else, supporting the action force:
- Generic term: *enabling force* / *enabling element*.
- *Disruption force/element*: operates in the disruption zone; disrupts enemy
  preparations/actions; destroys or deceives enemy reconnaissance; begins reducing the
  effectiveness of key enemy combat-system components. (Ties to Ch6 "Actions of the
  Disruption Force" and to systems warfare, ch1.)
- *Fixing force/element*: fixes the enemy by preventing part of his force from moving from
  a specific location for a specific time, so it cannot interfere with the primary action.
- *Security force/element*: protects other parts of the larger organization from
  observation, destruction, or becoming fixed.
- *Deception force/element*: conducts a deceptive action (demonstration or feint) that
  leads the enemy to act in ways prejudicial to his own interests or favoring the OPFOR
  action force's success.
- *Support force/element*: provides support by fire, other combat/combat-service support,
  or C2 functions for other parts of the larger organization.
- *Clearing element*: clears obstacles to permit an action element to accomplish a
  detachment's tactical task (example of a more specific enabling designation).

**Other**: *Reserve force/element* -- subordinates held out of initial action, status
pending, so the commander can influence unforeseen events/opportunities; on assignment of
a specific function they get relabeled accordingly (e.g. a reserve force committed to
counterattack in the defense becomes the *counterattack force*). *Protected force* --
in defensive actions, a unit/grouping the commander wants shielded from enemy observation/
fire so it survives to fight after the current battle. **Patrol** -- platoon- or
squad-size grouping task-organized for a specific recon and/or security mission; two
types, fighting patrol and reconnaissance patrol (ch8).

Key caveat (note, p.2-16): a force/element can be re-tasked mid-battle -- e.g. a
disruption force generally "disrupts" but may need to "fix" part of the enemy; in that
case the WHOLE disruption force could become the fixing force, or PART of it could become
a fixing element, while retaining its higher-echelon force/element identity as
appropriate.

## Zones within an AOR (para 2-36 to 2-48, p.2-13 to 2-15)

An AOR (area of responsibility, bounded by a limit of responsibility/LOR) typically
contains three basic zones plus optional attack/kill zones. Not all zones are required in
every situation (a command with no disruption zone might just have a battle zone; a
disruption force of a higher command might have NO battle zone of its own; battalion and
below AORs are often almost entirely battle zone with a small support zone inside).
- **Disruption zone**: AOR of the disruption force. Where the OPFOR sets conditions for
  success by fixing enemy forces and placing long-range fires on them; begins
  disaggregating the enemy combat system. Specific actions: attack enemy engineer
  elements (denying maneuver in complex terrain), strip enemy reconnaissance assets while
  denying his deep-fire targeting (including counter-air-recon/attack), force early enemy
  deployment or disrupt his offensive prep, gain/maintain recon contact with key enemy
  elements, deceive the enemy about OPFOR disposition. Bounded by the battle line and the
  overall AOR's LOR; boundaries can be "layered" (one command's disruption zone nests
  inside the next-higher command's disruption zone) and move forward/outward as an
  offense succeeds. Battalions and below normally do NOT have their own disruption zone
  but may conduct disruption tasks within a higher command's.
- **Battle zone**: where the OPFOR expects to conduct DECISIVE action, exploiting
  opportunities the disruption zone created. Goals: create a penetration for exploitation
  forces, draw enemy attention/resources, seize terrain, inflict casualties on a
  vulnerable enemy unit, prevent enemy repositioning elsewhere. Separated from disruption
  zone by the battle line, from support zone by the support line. A division/DTG battle
  zone may just be the aggregate of subordinate brigade/BTG battle zones (nonlinear
  situations can have multiple noncontiguous ones).
- **Support zone**: kept free of significant enemy action; permits effective logistics/
  admin support. Security forces here defeat enemy special operations forces in a combat
  role; C3D (camouflage/concealment/cover/deception) protects against standoff RISTA and
  precision attack throughout. May be dispersed within subordinate support zones, or
  separate/noncontiguous (a "sanctuary").
- **Attack zone**: given to a subordinate with an OFFENSIVE mission inside a larger
  defensive battle/operation, to delineate where it maneuvers offensively.
- **Kill zone**: a designated area where the OPFOR plans to destroy a key enemy target;
  can sit inside the disruption zone, battle zone, or (in the defense) the support zone.

## Command posts (Table 2-2 + para 2-119 to 2-172, p.2-28 to 2-34)

CP = three parts: control group (command group/section + staff), support group
(transport/logistics), communications group (often remoted for signature reduction). Five
basic + three special CP types, not all used at all echelons:
- **Main CP** (MCP): DTG/Division, BTG/Brigade, BDET/Battalion -- always. CDET/Company --
  never (company has no staff). Bulk of the staff; COS runs it; less mobile, in battle
  zone or a fortified sanctuary; focus is coordinating uncommitted subordinates and
  planning subsequent missions.
- **IFC CP**: DTG/Division ONLY (always). Run by the DC as IFC commander; integrates
  RISTA with long-range fires; typically separated from the main CP, and its own
  sub-sections need not be colocated with each other for survivability.
- **Forward CP** (FCP): all four echelons DTG/Division, BTG/Brigade, BDET/Battalion,
  CDET/Company -- always. Small group of selected staff (ops officer, chief of recon
  typically) deployed where the commander can personally observe/influence the battle;
  personnel not permanent.
- **Sustainment CP** (SCP/SUSCP): all four echelons -- always. Run by the resources
  officer; in the support zone; staffed with fuel/medical/equipment-repair/ammo/clothing/
  food/EPW and other service specialists; multiple sustainment CPs possible in nonlinear
  fights.
- **Airborne CP** (AIRCP): DTG/Division and BTG/Brigade -- maybe; BDET/Battalion and
  CDET/Company -- never. Common at DTG/division level, typically helicopter-borne, used
  when subordinates are widely dispersed or other CPs are moving.
  CORRECTION per table: BDET/Battalion = never for airborne, but "maybe" (X in parens)
  IS shown for BTG/Brigade; re-verify exact table cell pattern against the image if this
  matters downstream (recorded here from the rendered table: DTG/Div = (X) for airborne/
  alternate/auxiliary/deception all four; BTG/Bde = (X) for airborne/alternate/auxiliary/
  deception; BDET/Bn = "-" for airborne, (X) alternate, "-" auxiliary, (X) deception;
  CDET/Co = "-" airborne, "-" alternate, "-" auxiliary, (X) deception).
- **Alternate CP** (ALTCP): a DESIGNATION given to an existing CP (not separately
  established) that assumes command if the CP containing the commander is destroyed/
  disabled.
- **Auxiliary CP** (AUXCP) and **Deception CP** (DCP): special-purpose, maybe-present at
  various echelons per table (deception CP possible at all four echelons; auxiliary only
  at DTG/Division and BTG/Brigade).

Communications nets (para 2-153 to 2-164): primary command net (forward CP, commander),
alternate/command net (main CP, COS), operations net (ops officer), integrated fires net
(DC/IFC), support net (resources officer), intelligence net (chief of recon), airspace
control net (CAO), special mission net (COS, ad hoc for detachments/airborne-heliborne
landing forces behind enemy lines), air defense and CBRN warning net (all units, COS
watches at main CP), plus INFOWAR deception nets. C2 survivability rests on mobility,
redundancy, and strict operations/information security (C3D) -- commander/DC/COS
deliberately split across forward/IFC/main CPs respectively so no single loss decapitates
command.

## Staff structure summary (ch2, p.2-17 to 2-27) -- see force-template records for the
full org chart (htfs_dtg_division_command_staff, htfs_battalion_command_staff); this is
role narrative context only.

DTG/division staff = Command Group (Commander, DC [=IFC commander], COS) + Primary Staff
(Intelligence Officer, Operations Officer [=deputy COS], Resources Officer) + Secondary
Staff (2-3 subsections per primary officer) + Functional Staff (6 subject-matter chiefs:
integrated fires, force protection, special-purpose operations, WMD, population
management, infrastructure management) + non-permanent Liaison Teams (1 chief + 2x
current-ops + 2x future-ops officers/NCOs per team) attached from subordinate/supporting/
allied/interagency/affiliated units. BTG/brigade staff = smaller version; DC does NOT
command an IFC (none exists below division); functional staff swaps "chief of integrated
fires" for a "chief of fire support coordination" element inside the operations section;
plans only 24-48hr ahead (vs DTG/division, which plans further out) vs battalion 6-24hr.
Battalion/BDET staff = Command Section (Cdr, DC, COS+staff, subordinate commanders) +
Primary Staff (Intel, Ops/deputy-COS, Resources) + Secondary Staff ONLY (no functional
staff below brigade/BTG) -- secondary staff roles are dual-hatted onto specialty platoon
leaders: chief of reconnaissance = recon platoon leader, chief of communications = signal
platoon leader, chief of fire support = mortar battery commander (or asst ops officer if
no mortar battery), chief of logistics = materiel support platoon leader (resources
officer may also cover chief of administration). Company/CDET = Headquarters and Service
Section only: Command Team (Co Cdr + staff NCO), Support Team (DC + 1SG), Supply and
Transport Team (supply sergeant) -- no staff, per definition of "company."

## Chapter 3 (Offense) -- functional-element role definitions by action type

Types of offensive action at TG/division/brigade level: **integrated attack** (military
decision by destroying enemy will/ability via combined arms effects; used when OPFOR has
overmatch or a created window of opportunity) and **dispersed attack** (used when OPFOR
lacks overmatch; multiple small, widely separated elements converge on the objective).
OPFOR has no separate "exploitation" or "pursuit" COA -- both are folded into
integrated/dispersed attack. **Strike** and **spoiling attack** and **counterattack** are
limited-objective attacks (para 3-9/3-10): a spoiling attack preempts an imminent enemy
attack; a counterattack restores a defense; both share similar functional organization.

- *Functional organization for an integrated/dispersed attack* (para 3-66/3-79 to 3-84):
  Enabling = **fixing force** (fixes enemy response forces/reserves with minimum combat
  power; dispersed attacks often use multiple fixing forces separated in time/space) +
  **assault force** (BTG level; destroys a part of the enemy or seizes key positions to
  create conditions for the exploitation force; may use infiltration) + **support force**
  (fire, CSS, or C2 support; smoke/suppressive arty/rocket fires, engineers, air-delivered
  weapons). Action = **exploitation force** (the most common action force; bypasses/
  destroys the target -- may be a maneuver brigade moving as dispersed platoons, or a
  widely dispersed group of SPF teams hitting simultaneous logistics targets).
- *Functional organization for a counterattack/spoiling attack* (para 3-98 to 3-104):
  same triad (fixing/assault/support enabling forces; exploitation force as action force)
  but fixing force = the force ALREADY engaged in defensive contact (also destroys any
  enemy recon/combat forces that penetrated); assault force (if used) forces the enemy to
  commit his reserve; disruption force (if any) came from the prior defensive posture.
- *Functional organization for an assault* (detachment/battalion and below, para 3-108 to
  3-111; also governs ambush/raid at this echelon, which are types of assault): **assault
  element** (the action element -- maneuvers to and seizes/destroys the enemy position),
  **security element** (early warning + prevents enemy reinforcement of the assaulted
  unit; may only be strong enough to warn, not repel, per commander's risk acceptance),
  **support element** (C2, CSS, direct fire support, indirect fire support, and/or
  mobility support to the assaulting detachment).
- *Ambush* (para 3-142 to 3-158): same assault/security/support triad, specialized --
  security elements take position FIRST, then ambush elements move in; kill zone execution
  triggered when enemy main body head reaches a predetermined point. Two ambush types:
  **annihilation ambush** (close-range, destroys the enemy force -- uses IEDs, hunter-
  killer infantry antiarmor teams) and **harassment ambush** (greater standoff range, no
  need to canalize the enemy into a kill zone with obstacles, used when enemy has superior
  combat power -- interferes with routine enemy activity/movement, psychological effect).
- *Raid*: same assault(raiding)/security/support triad; raiding element = fire support
  units/aviation acting alone or with ground forces; armor, air defense (in security
  element), engineers (mobility in/out), logistics (self-contained, not multi-day),
  INFOWAR (conceals the action, publicizes success afterward) all support roles defined
  para 3-187 to 3-192.
- *Reconnaissance attack* (para 3-193 to 3-206): locates moving/dispersed/concealed enemy
  elements and fixes or destroys them; most ambitious and least-preferred way to gain
  information (used when other recon means failed). Elements: **action element**
  (maneuvers on fixed enemy forces to destroy them -- may be the same armored force that
  fixed them, given mobility/speed), **security element** (may perform its own recon
  tasks -- find AND fix -- or a separate reconnaissance element finds while security fixes),
  **support element**.

## Chapter 4 (Defense) -- functional-element role definitions

Two types: **maneuver defense** (used when not completely overmatched; skillfully uses
fires/maneuver to destroy key enemy combat-system elements and deny objectives while
preserving friendly force; can economize force on secondary axes) and **area defense**
(used to deny key areas or when overmatched; forces enemy offensive culmination OR denies
enemy objectives while preserving combat power for a later decision).

- *Maneuver defense functional org* (para 4-70 to 4-84): **Defensive maneuver** = movement
  by bounds + continuous fires, executed by splitting a force (disruption force and/or
  main defense force) into a **contact force** (occupies the defensive array in current/
  imminent contact -- forces enemy deployment, then displaces to the next array before
  becoming decisively engaged) and a **shielding force** (occupies the NEXT array,
  protecting the contact force's displacement with continuous observation/fires/attack;
  becomes the new contact force once the original contact force arrives -- roles rotate
  bound to bound; shielding force need not stay static, it can meet the enemy in an ambush
  then displace). Disruption force initiates the attack on the enemy combat system in the
  disruption zone (may pass into hide positions if heavily damaged, letting main
  defense/reserve cover its disengagement). Main defense force completes the enemy's
  defeat, also splits into contact/shielding forces. Maneuver reserve = strong enough to
  defeat the enemy's exploiting force; held in a protected assembly area (C3D), transitions
  to situational defense or counterattack.
- *Area defense functional org, SBP (security battle position) example* (para 4-113 to
  4-116): **CSOP** (combat security outpost, forward, provides early warning + engagement
  fan/kill zone, may include dummy positions), **ambush teams** (independent of CSOPs,
  concealed forward of the battle zone, allow bypass then flank/surprise-fire key targets),
  **main defense element** (defeats the attacking force; maneuvers to defeat penetration or
  seizure of other SBPs), **reserve element** (tactical flexibility -- counterattack,
  counterpenetration, antilanding defense, assist breaking contact, or act as a deception
  element), **support element** (CSS, C2, direct/indirect fire support, nonlethal support
  e.g. jamming/psywar/broadcasts, engineer support).
- *Area defense functional org, CBP (combat battle position) example* (para 4-149 to
  4-153) -- same five-part pattern relabeled as ELEMENTS not separately-named
  posts/teams: **disruption element** (detects attackers, early warning; forms CSOPs and
  ambush teams itself, plus antilanding ambushes/reserves; stays in position through the
  attack to keep providing recon), **main defense element**, **reserve element**,
  **support element**. CBPs are generally independent/self-supporting/low-signature
  (non-emitting air defense, concealed engineer works, self-sustaining logistics, low-
  profile or population-embedded INFOWAR) compared to SBPs.

## Chapter 5 (Battle Drills) -- functional-element role definitions

Battle drills = detachment-level tactical tasks executed by functionally-organized
elements; composition varies by unit/environment but the SUBTASK each element performs is
standardized OPFOR-wide (para 5-3). Seven forms of contact: direct fire, indirect fire,
obstacle, air, CBRN, electronic warfare, visual (para 5-5, ch3 3-55 lists visual instead
of implying all 7 -- both chapters cross-reference the same seven-forms list). Drills
include: **actions on contact** (security element makes first contact, provides early
warning, prevents further enemy information gain), **breaking contact**, **situational
breach** (elements: support element establishes a support-by-fire position and neutralizes
obstacle-defending enemy; breaching element physically reduces the obstacle so the action
element or a follow-on force can pass), **fire and maneuver** (splits the force into a
**firing element**, which fires from cover/concealment to suppress, and a **moving
element**, which displaces to the next firing line -- roles alternate each bound until the
objective is reached; this is the most basic OPFOR battle drill), **fixing** (enemy forces).

## Chapter 6 (Other Combined Arms Actions) -- Counterreconnaissance (CR)

CR = continuous combined arms action to locate, track, and destroy all enemy
reconnaissance in a given AOR; conducted at all times, all operation types (para 6-8).
Control measures: **counterreconnaissance zones (CRZs)** (AOR subdivisions, one CRZ =
one CRD's responsibility -- may equal the whole DTG/BTG AOR, or the disruption zone, or
each brigade/BTG's own zone), **reference zones (RZs)** (grid-pattern subdivisions of a
CRZ for rapid orientation/target designation), **predicted enemy locations (PELs)**,
**kill zones**. Disruption force composition for CR (para 6-4, no set order of battle):
ambush teams (ground + air defense), long-range recon patrols and/or SPF teams, RISTA
assets/forces, counterreconnaissance detachments, artillery systems, target designation
teams, affiliated-force elements (insurgents/guerrillas/criminals/local sympathizers),
antilanding reserves. **Counterreconnaissance detachment (CRD)**: task-organized
detachment responsible for one CRZ; example org in force-template chunk
htfs_counterreconnaissance_detachment (mech inf co + tank plt + SP AA plt + ATGM plt + SP
122mm howitzer btry) -- actual composition varies (para 6-18): reconnaissance
(long-range/mounted/dismounted/signals/aerial/SPF -- most essential component), air
defense (defensive OR offensive vs enemy UAV/recon aircraft/helicopters), aviation (rapid
transport to located targets, armed/unarmed recon, resupply of dispersed CRD elements),
artillery (kills recon without direct-fire engagement; precision preferred). CRD may
absorb the security force mission entirely or work alongside a separate security force.

## Chapter 7 (Information Warfare) -- reference only, no org structures

Table 7-1 (p.7-2/7-3) lists INFOWAR elements with their objectives and targets:
**electronic warfare** (deny/degrade enemy info systems; targets: enemy C2, RISTA, nav,
IFF, precision-weapon guidance links), **INFOWAR-related computer warfare attack**
(targets enemy computer/info networks), **INFOWAR-related physical destruction**
(precision fires + special operations against enemy C2/RISTA nodes/nets), **protection
and security measures / OPSEC / camouflage / concealment / cover / deception (C3D)**
(protects own C2/RISTA/decision-making), **perception management** (targets adversary/
domestic/int'l/regional perceptions), **deception**, **INFOWAR-related physical
destruction of civilian infrastructure supporting enemy info systems**. No org figures --
confirms structure map (INFOWAR chapter is pure doctrine/reference-table, no task-org
diagrams; EW/INFOWAR units are functionally described, not charted).

## Chapter 8 (Reconnaissance) -- reference only, no org structures

No fixed TOE given for the division/DTG reconnaissance battalion or brigade/BTG
reconnaissance company -- text explicitly states these "vary in size and composition from
a few scouts to a battalion," task-organized per mission (consistent with TC 7-100.4
covering the organic TOE, if any). Reconnaissance element/patrol taxonomy (used
throughout the pub wherever "security element" or "reconnaissance element" appears):
**patrol squad**, **reconnaissance team**, **reconnaissance patrol**, **independent
reconnaissance patrol (IRP)**, **officer reconnaissance patrol**, **fighting patrol**
(same "fighting patrol" as ch2's generic patrol definition). Fig 8-1 (effective ranges of
example recon assets) is a reference chart, not an org diagram -- lists division/DTG
reconnaissance battalion and brigade/BTG reconnaissance company as IRP-fielding
organizations without detailing their internal structure.

## Chapter 9 (Indirect Fire Support) -- command/control confirms IFC pattern; no new
functional-element vocabulary beyond ch2/ch3. Command/support relationships mirror
Table 2-1 (constituent/dedicated/supporting only -- affiliated not applicable to fire
support units). Text explicitly cross-references FM 7-100.4 for indirect-fire weapons "in
OPFOR organizations" (para 9-16/9-17) -- confirms TC 7-100.2's contribution here (the
IFC C2/task-org structure, chunk_0004) does not duplicate 7-100.4's organic artillery
battalion/brigade TOEs. Deception/false battery techniques (para 9-132 to 9-134): the
"fourth battery" technique (splitting a battery into two platoons + borrowed weapons to
mimic a fourth battery) and false/decoy battery (active + decoy firing positions) --
tactics, not org structure.

## Chapter 10 (Aviation) -- command/support relationships identical triad to ch2/ch9
(constituent/dedicated/supporting; no affiliated relationship for aviation). Key
employment point (para 10-14): a highly-trained attack helicopter unit MAY be employed as
a maneuver element in the ground scheme of maneuver -- filling ANY of the standard
functional roles (disruption, fixing, assault, or exploitation force in the offense;
reserve, counterattack, or deception force in the defense) -- requires thorough
planning/rehearsal. UAV employment (para 10-19/10-20): OPFOR operates UAVs at all levels
from strategic down through division/brigade/battalion/some companies to SPF teams;
constituent/dedicated at the assigned echelon, or supporting status down to individual UAV
team level. Airspace management: CAO (chief of airspace operations) sits on the OSC
staff (lowest joint-command echelon) under the operations officer -- ties to ch2 staff
chart (chief of airspace operations already captured as DTG/division secondary staff).

## Chapter 11 (Air Defense) -- text confirms NO org figures; explicit cross-reference
"For specifics on tactical organizations, see FM 7-100.4" (para 11-61). Air defense asset
distribution by echelon (para 11-62 to 11-66, narrative only, no chart): **division** --
most maneuver divisions contain at least an air defense BRIGADE (fully covers the whole
division); **divisional/separate brigade** -- organic air defense BATTALION (separate
brigades' battalions typically more robust than divisional brigades'; an augmented
separate-brigade BTG's air defense may equal a full AD brigade); **battalion** -- typically
a MANPADS PLATOON for self-protection, sometimes augmented; **company** -- MANPADS squads
may be pushed down from the battalion platoon, plus all-arms air defense (7.62mm
general-purpose MGs on most tactical vehicles, massed small-arms fire under company
commander supervision against low-flying aircraft). Table 11-1 (example security
measures) and Table 10-3-style readiness tables are reference/procedural, not org.

## Chapter 12 (Engineer Support) -- text confirms NO org figures; para 12-16 places
engineer officers as permanent functional-staff members (chief of force protection AND
chief of infrastructure management subsections) -- ties to ch2 staff chart. **Chief of
Engineer Liaison Teams (CELT)**: senior engineer liaison-team leader, primary staff
advisor to the operations officer and maneuver commander on engineer employment; in units
without liaison teams the senior engineer serves as CELT. Named task-organized engineer
groupings (para 12-24, cross-referenced from ch2's BDET/CDET augmentation menu): **obstacle
detachment (OD)**, **movement support detachment (MSD)**, **engineer reconnaissance patrol
(ERP)** -- engineer assets generally constituent no lower than brigade level, but OPFOR
prefers to task-organize down to multirole engineer support elements as small as platoons/
squads when assets allow (para 12-21/12-22).

## Chapter 13 (CBRN and Smoke) -- text confirms NO org figures (all figures are TAC
formation/vignette diagrams, e.g. fig 13-5/13-10 smoke employment examples). Staff
placement confirmed (para 13-8/13-9, matches ch2 chart): **chief of WMD** (functional
staff) plans offensive CBRN/WMD employment; **CBRN defense** falls under **chief of force
protection**. Both receive liaison teams from subordinate/supporting CBRN-capable units.

## Chapter 14 (Logistics) -- functional roles matching the staff chart (resources officer
= division logistician's boss; chief of logistics; chief of administration -- see
htfs_resources_section). ISC/ISG detail: ISC HQ (htfs_integrated_support_command_hq) =
standing C2 nucleus; ISG (htfs_dtg_isg_example) = the actual task-organized CSS units,
NO STANDARD STRUCTURE (para 14-30) -- composition varies with the tactical support
situation and, for a DTG, with the DTG's own task organization; normally one ISG supports
the division/DTG proper and a second supports the IFC. ISG has six major functions:
supply, maintenance, transportation, medical support, personnel services, field services
(may also take on engineer, chemical warfare, law enforcement, RISTA, or INFOWAR tasks).
Logistics doctrine concepts: centralized planning / decentralized execution, support
forward, sustainment from other sources (foraging, captured supplies, civilian
procurement/coercion). Supply priorities in order: ammunition, POL, spare parts/technical
supplies, rations/clothing/medical. Distribution methods: supply point, unit distribution,
throughput. For additional ISC organizational detail, text explicitly cross-references FM
7-100.4 (para 14-26) -- confirms non-duplication.

## Chapter 15 (Special-Purpose Forces and Commandos) -- employment doctrine

**SPF** (Section I, 15-1 to 15-24): basic missions include direct action, special
reconnaissance, unconventional warfare support (organize/train/advise/support/control
irregular forces as surrogates -- terror tactics possible per note p.15-4), serving as
part of an IFC at OSC level and sometimes DTG level, terminal guidance for aircraft/
missile/precision-weapon attacks. Special missions: **special reconnaissance** (deep
behind enemy lines, HUMINT eyes-on-target, long-range recon in small teams beyond the
AOR's battle lines; priorities: CBRN delivery systems, precision weapons, HQ/C2, RISTA,
movement routes, airfields/ports, logistics, air defense) and **direct action**
(assassination, abduction/hostage-taking, sabotage, capture, ambush, raid). KEY
DEFINITIONAL NOTE (p.15-6): "in most OPFOR organizations, a detachment is a battalion or
company designated to perform a specific mission... However, SPF are organized into
companies and battalions for ADMINISTRATIVE purposes only, not for performing missions.
Therefore, a detachment in SPF terms is a temporary grouping of SPF teams that is
task-organized for a particular mission but is not necessarily linked to a company or
battalion organization." SPF assets reach the tactical level normally via the OSC (an OSC
is the lowest level of JOINT command, so it can draw SPF from Army SPF, national-level SPF
Command, or Air Force/Navy SPF). SPF org charts (fig 15-1 to 15-4) explicitly drawn from
FM 7-100.4 (para 15-32) -- SPF brigade/battalion/company/team structures are NOT fixed
TOE, all dashed boxes = mission-dependent optional. Swarming tactic (massed swarm vs
dispersed swarm -- dispersed preferred, hardest to defend against). Stay-behind SPF teams
pre-position before enemy occupation to organize an affiliated irregular nucleus, conduct
surveillance, or direct action.

**Commandos** (Section II, 15-25 to 15-35 area): reconnaissance + combat missions in the
disruption zone or deep in enemy territory. Employed as functional forces/elements in
combined arms actions -- same vocabulary as ch2/ch3/ch4: commandos can act as a
**disruption force or element** (create confusion, remove/emplace obstacles, raid HQ/LOC/
missile sites, occupy key terrain or ambush positions on withdrawal routes), a **fixing
force or element** (ambush/obstacles to block enemy reinforcement, occupy choke-point
terrain), or part of an **action force or element** (raids/surprise attacks on C2, logistics,
fire support incl. attack helicopter units, high-priority targets). In the DEFENSE,
commando units allocated to a tactical group/detachment task organization primarily fill
reconnaissance and security roles (recon in the disruption zone or deep territory; security
force in the support zone, normally employed as companies or battalions when in this role,
can be augmented with tank/mechanized/fire-support/aviation to become an action force
against enemy airborne/air-assault/SOF incursions). Stay-behind commandos: same concept as
SPF, remain in the original disruption/battle zone after a friendly withdrawal to continue
recon/raids/ambushes in small teams.

KEY EMPLOYMENT FACT (para 15-171): "No commando assets are constituent to tactical level
units at division and below in the AFS. All commando assets employed at the tactical level
will have been allocated from higher levels" -- i.e. commandos (like SPF) always arrive at
the tactical fight via task organization/allocation, never organic to a division/brigade.
Commando brigades/battalions/companies "exist in the AFS" but with NO FIXED STRUCTURE
(para 15-170) -- figs 15-5 through 15-12 all show dashed/optional boxes; only fig 15-13
(high-mobility recon platoon) is drawn without dashed boxes. Commando infiltration TTP:
land (most common, by foot, small teams via difficult terrain/gaps between enemy units;
"probe" infiltration technique -- small teams test enemy response, then mass exploits weak
points; the "wait behind enemy lines" variant can hold in place hours to 3+ days at up to
battalion size before ambushing a retreating enemy or double-enveloping a faltering
friendly main attack) and air (airdrop/air-land for deeper penetration).

Personnel/equipment scale note for SPF DAR platoon (para 15-39): less than 40 personnel, 14
vehicles -- the only hard personnel number given anywhere in ch15's org figures (all other
figures are structural only, no headcounts, consistent with "no fixed TOE" throughout the
chapter).

## Chapter 16 (Marksmen and Snipers) -- reference only, no org structures

Text explicitly cross-references FM 7-100.4 for OPFOR organizations/equipment (para 16-7)
-- confirms no duplicate org content. Marksman/sniper rifle ALLOCATION BY ECHELON (para
16-7, prose-embedded quantitative data, captured here since it is genuine organizational/
holdings data even though not charted): every OPFOR infantry squad (infantry, motorized
infantry, or mechanized infantry company) = 1 marksman + 1 assigned 7.62-mm sniper/
marksman rifle. Infantry or motorized infantry company additionally has a weapons platoon
with 2 sniper/marksman rifles + 2 12.7-mm/.50-cal antimateriel rifles -- company total 11
sniper/marksman rifles + 2 antimateriel rifles; battalion total (x3 companies) = 33
sniper/marksman rifles + 6 antimateriel rifles. Mechanized infantry company = 9 sniper/
marksman rifles (1 per squad, no weapons-platoon add per this text); mechanized infantry
battalion weapons platoon = 3 antimateriel rifles; battalion total = 27 sniper/marksman
rifles + 3 antimateriel rifles. Marksmen also exist in non-maneuver supporting units
(not infantrymen, just soldiers trained/equipped as marksmen); OPFOR trains women as
markswomen, no gender restriction. Table 16-1 (regular military sniper vs irregular-force
sniper comparison) is reference-only, not org: team composition line notes irregular
sniper teams run "individual or team of 2 to 4 (shooter, driver/spotter/security,
support, video, possibly cell leader/trainer)" vs regular military "individual sniper to
a sniper team of 4 or more."

---

## END OF EXTRACTION -- chapters 1-16 (full document body) processed. Glossary/References/
Index (back matter) confirmed to contain no organizational figures on spot-check (glossary
is a flat acronym/term list). See tc71002_structure_map.md for the complete figure-by-
figure classification and chapter page ranges, and extraction_ledger_tc71002.json for the
final chunk inventory.
