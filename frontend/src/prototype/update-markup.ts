// Preserve the cabinet shell, focus and scroll while applying API/template updates.
// The input is our sanitized template; API values are inserted by bindBank as text.
export function updateMarkup(parent: Node, next: Node) {
  const children = Array.from(parent.childNodes);
  const incoming = Array.from(next.childNodes);
  for (let index = 0; index < Math.max(children.length, incoming.length); index++) {
    const current = children[index];
    const replacement = incoming[index];
    if (!replacement) { current.remove(); continue; }
    if (!current) { parent.appendChild(replacement.cloneNode(true)); continue; }
    if (current.nodeType !== replacement.nodeType || current.nodeName !== replacement.nodeName) {
      parent.replaceChild(replacement.cloneNode(true), current);
      continue;
    }
    if (current instanceof Element && replacement instanceof Element) {
      const editing = current === document.activeElement;
      const previousValue = current.getAttribute("value");
      const previousChecked = current.hasAttribute("checked");
      for (const attribute of Array.from(current.attributes)) {
        if (!replacement.hasAttribute(attribute.name) && !(editing && attribute.name === "value")) current.removeAttribute(attribute.name);
      }
      for (const attribute of Array.from(replacement.attributes)) {
        if (editing && attribute.name === "value") continue;
        if (current.getAttribute(attribute.name) !== attribute.value) current.setAttribute(attribute.name, attribute.value);
      }
      if (!editing && current instanceof HTMLInputElement && replacement instanceof HTMLInputElement) {
        if (current.type !== "file" && previousValue !== replacement.getAttribute("value")) current.value = replacement.value;
        if (previousChecked !== replacement.hasAttribute("checked")) current.checked = replacement.checked;
      }
      if (editing && current.matches("textarea, select")) continue;
      updateMarkup(current, replacement);
    } else if (current.nodeValue !== replacement.nodeValue) current.nodeValue = replacement.nodeValue;
  }
}
