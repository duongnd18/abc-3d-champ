Image 1 is the reference photo of the target object. Images 2 to {last} each show one candidate 3D model as a 2x2
sheet of renders: top-left front-left 30°, top-right front-right 30°, bottom-left from the front 15° below,
bottom-right from the front 30° above. Candidate k is image k+1.

For EACH candidate: how faithful a 3D reproduction of the reference is it? The right kind of object, overall shape
and proportions, the same side facing the viewer, distinctive parts and their counts, colours and materials.

{features}Penalty 0-10 per candidate (one decimal):
0 = Perfect match to reference
3 = Minor issues (slight shape differences, missing small details)
5 = Moderate issues (wrong style, significant details missing)
7 = Major issues (wrong category but related, e.g. chair vs stool)
10 = Completely wrong object

Return JSON: penalties, one number per candidate, in candidate order.
