BUILD PLAYBOOK (what consistently wins with this judge):
1. Dimensions first: start build() with `const D = {...}` holding the real proportions measured from the photo,
   and derive every part's size and position from D. Silhouette and proportions before details.
2. Pose: build the object in its natural pose so that a camera on +Z sees it the way the photo shows it: the same
   side facing the viewer, the same upright, lying or profile pose and the same left-right direction (Y up). Dials,
   screens, labels and faces shown head-on in the photo face +Z. The judge's cameras are 30° left and 30° right of
   +Z at object height, 15° below the front and 30° above it. When the photo looks down on the object (it shows the
   top, lid, opening, seat, tray or top surface), put the whole model in one group and tilt it towards the camera
   with group.rotation.x = +(the photo's downward angle minus about 10°, usually 10-25°, in radians); positive tips
   the top towards +Z. Balance the two vertical cameras: the camera 15° below the front must still see the top
   features the photo shows, and the camera 30° above must not see much more of the top than the photo does.
   Objects lower than half their width or depth are already tipped 15° by the pipeline: add only the tilt beyond 15°.
3. Use the helper library: lathe / hollowLathe for round bodies (bottles, cups, vases, lamp stems; vessels get a
   real wall and an open rim), tube for handles, cords, wires and rims, extrudeOutline for flat outlines, plates,
   blades and logos (with holes instead of dark patches), roundedBox for device shells instead of raw boxes,
   ringOf for repeated parts around an axis, mat for every material, patternTexture for wood grain, stripes or
   speckle. Every part touches its parent; no floating parts.
4. Surface decoration (bands, labels, buttons, rivets, emblems) sits ON the surface: compute its position from
   the body's radius/height at that spot, orient it along the surface normal, offset ≈0.3% of the object size.
5. Realism over toy look: bevel and round visible edges, add seams, panel lines, rims, screws, grooves, lips,
   thickness at openings and the small protruding parts a real product has.
6. Be thorough: write a detailed build(THREE) of about 6,000-9,000 tokens of code. In the last round the entries
   that wrote the most detailed code won. Spend the length on what the photo shows: every distinct part with its
   real profile, bevels and rounded edges, rims and lips, seams and panel lines, buttons, knobs, keys, screws and
   rivets, holes and vents, feet, hinges and handles, labels and printed patterns (patternTexture or thin surface
   geometry). Use your own helper functions and loops so the length goes into detail, not repetition. Dense
   assemblies (electronics, cables, machinery, shelves or boxes full of items, bouquets, piles of food) fill the
   visible volume as densely as the photo shows, spread over the whole object, never bunched in the centre with
   empty gaps the photo does not have; build their many small parts as InstancedMesh with low segment counts
   (item 11), so density costs no vertices.
7. Tops and undersides: the judge also looks from 30° above and 15° below, and a duel is only won when every view
   agrees. Model the top (lids, rims, openings, interiors, contents, the inside of a bowl) and the underside (base,
   foot ring, feet, wheels) as carefully as the front.
8. Materials (via mat): metal 'chrome'/'steel'/'brushed'/'brass'/'gold'/'copper' with the photo's colour, lifted
   if it is dark. The presets keep metalness ≤ 0.6 on purpose (fully metallic surfaces render as dark mirrors and
   lose duels): never set metalness above 0.6. Hollow glass and clear plastic (bottles, globes, jars, shades):
   'glass', a tinted see-through shell, built as thin hollow walls (hollowLathe or thin shells) so the inside and
   the contents show, never as a solid block. Solid gems and crystals keep their saturated colour. Glossy plastic
   'gloss', ceramic 'ceramic', lamps/screens 'emissive',
   fabric/wood/rubber 'fabric'/'wood'/'rubber'. Match the photo's hue and brightness; never darker than the photo.
   Pale objects need visible shading and edges, not a flat grey blob.
9. There are no booleans: openings are holes or revolved walls, recesses are real geometry. Thin sheets (leaves,
   flags, paper) need side: THREE.DoubleSide. Thin parts (rods, wires, rims, straps, frames, blades, clock hands)
   need a thickness of at least 1.2% of the object's largest size, or they shrink to a hairline in the judge's
   views; build visible structure from meshes, never from Line/LineSegments (one pixel wide).
10. API traps: CylinderGeometry/ConeGeometry axis is Y (wheels need rotation.z = π/2); PlaneGeometry/
   CircleGeometry lie in XY; THREE is usable only inside functions that receive it as a parameter named exactly
   THREE; no Math.random; Shape/Path have no translate() (offset the points or the mesh instead). Never name
   your own variables window, self, global, module, document, process or Date:
   the checker rejects those names anywhere.
11. Stay inside the organiser's limits with a margin: ≤150k vertices and ≤150 draw calls (the hard limits are 250k
   and 200; detailed modules of devices, racks and grilles overshoot most often). Detail comes from more parts and
   better profiles, not from more vertices: anything repeated more than a few times (vents, holes, slots, screws,
   keys, LEDs, studs, tiles, bars, rivets) is ONE geometry in an InstancedMesh or ringOf, because instances add no
   vertices and count as one draw call; share geometries and materials; 32–64 radial segments for big round parts,
   8–16 for small ones. Rough costs: SphereGeometry(r, 32, 16) ≈ 560 vertices, a box 24, a TubeGeometry about
   tubular × radial segments, an ExtrudeGeometry with bevel several thousand. Textures: at most 2–3 patternTexture
   calls (size ≤ 256), each created once and shared; one texture per mesh or per clone quickly passes the 4 MB
   limit and is rejected. No ground planes, boxes, walls, backgrounds or floating text that are not part of the
   object.
12. Text and logos: copy every word, number and logo the photo shows letter by letter, with the same spelling
   (misspellings included), case, colour, size and position; never invent text. Paint it into a DataTexture (your
   own small bitmap font) or build it from thin shapes on the surface, large enough to read in a 1024 px view.
