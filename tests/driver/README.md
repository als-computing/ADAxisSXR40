# driver/ — needs the camera; marked `fork_fix`

The reasons this fork exists, one test each: ROI alignment (width 8, height/offsets 4),
the height clamp not corrupting the width, AutoLevels publishing the Histogram readback,
FrameFormat bounds, exposure quantised to the row time, NO_RESOURCE tolerated. Against
Damon's ADTucsen these become expected failures naming the defect; an XPASS there means
his driver has since fixed it.
