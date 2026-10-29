// The home page's opening animation switch (app/page.tsx): on while the page loads, off 3.2 s later (MOTION_DONE_MS) whatever
// state the animation is in, so content never waits on it; without this script there is no animation at all.
(function () {
  var MOTION_DONE_MS = 3200;
  var h = document.documentElement;
  h.classList.add("motion");
  setTimeout(function () { h.classList.add("motion-done"); }, MOTION_DONE_MS);
})();
