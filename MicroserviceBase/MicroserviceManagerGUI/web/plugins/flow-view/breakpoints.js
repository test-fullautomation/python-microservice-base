// flow-view: breakpoints on the steps, and the step a debugger paused at.
// Only for a host that debugs (the VS Code extension): it pushes
// `breakpoints` (the ids of the steps that have one; a step of an opened
// sub-flow as "<sub-flow>::<id>") and `paused` (the step the run is stopped
// at, or null) with the flow, and gives ctx.breakpoint(id). Every step then
// gets a dot at its top-left corner, like an editor's gutter: faint while the
// pointer is on the step, red when it has a breakpoint; clicking it asks the
// host to set or remove one. Without `breakpoints` nothing is drawn.
//
// No layout here: the dots sit on the nodes flow.js drew ([data-node]).

var SVG = 'http://www.w3.org/2000/svg';

function shape(g) {
  return g.querySelector('rect, polygon');
}

/** Draw the dots and the paused mark on the nodes under `scope`. */
export function markBreakpoints(scope, data, toggle) {
  var on = Array.isArray(data && data.breakpoints);
  var set = Object.create(null);   // ids from the flow: no inherited keys
  (on ? data.breakpoints : []).forEach(function (id) { set[id] = true; });
  var paused = data && data.paused;
  scope.querySelectorAll('[data-node]').forEach(function (g) {
    var id = g.getAttribute('data-node');
    var dot = g.querySelector('circle.fv-bp');
    g.classList.toggle('fv-paused', !!paused && paused === id);
    if (!on) {
      if (dot) dot.remove();
      g.classList.remove('fv-has-bp');
      return;
    }
    if (!dot) {
      var box = shape(g);
      if (!box) return;
      var b = box.getBBox();
      dot = document.createElementNS(SVG, 'circle');
      dot.setAttribute('class', 'fv-bp');
      dot.setAttribute('cx', String(b.x + 1));
      dot.setAttribute('cy', String(b.y + 1));
      dot.setAttribute('r', '6');
      var title = document.createElementNS(SVG, 'title');
      title.textContent = 'Breakpoint: click to set or remove';
      dot.appendChild(title);
      if (toggle) {
        dot.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          toggle(id);
        });
        // A click on the dot is not a click on the step (which finds it in the text).
        dot.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
      }
      g.appendChild(dot);
    }
    g.classList.toggle('fv-has-bp', !!set[id]);
  });
}
