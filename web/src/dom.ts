// Tiny DOM helper — `h("div.foo", {...}, children)` keeps screen code terse.

type Child = Node | string | number | false | null | undefined;
type Props = Record<string, unknown>;

export function h(
  selector: string,
  props: Props | Child[] | Child | null = null,
  ...children: Child[]
): HTMLElement {
  // Parse "tag.class#id" — tag is the leading run of letters/digits before
  // the first "." or "#". Anything after is classes/ids.
  const firstMark = selector.search(/[.#]/);
  const tagPart = firstMark === -1 ? selector : selector.slice(0, firstMark);
  const rest = firstMark === -1 ? "" : selector.slice(firstMark);
  const tag = tagPart || "div";

  const el = document.createElement(tag);

  const classes: string[] = [];
  let id: string | undefined;
  rest.replace(/[.#][^.#]+/g, (m) => {
    if (m[0] === ".") classes.push(m.slice(1));
    else id = m.slice(1);
    return "";
  });
  if (classes.length) el.className = classes.join(" ");
  if (id) el.id = id;

  // props may actually be children if it's an array or not a plain object
  let actualProps: Props | null = null;
  let leading: Child[] = [];
  if (
    props !== null &&
    props !== undefined &&
    !Array.isArray(props) &&
    typeof props === "object" &&
    !(props instanceof Node)
  ) {
    actualProps = props as Props;
  } else if (props !== null && props !== undefined) {
    leading = Array.isArray(props) ? props : [props as Child];
  }

  if (actualProps) {
    for (const [k, v] of Object.entries(actualProps)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className += " " + String(v);
      else if (k === "style" && typeof v === "object")
        Object.assign(el.style, v as Record<string, string>);
      else if (k.startsWith("on") && typeof v === "function")
        el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
      else if (k === "html") el.innerHTML = String(v);
      else if (k in el) (el as unknown as Record<string, unknown>)[k] = v;
      else el.setAttribute(k, String(v));
    }
  }

  const allKids = [...leading, ...children];
  for (const c of allKids) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }

  return el;
}

export function clear(el: HTMLElement): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

export function mount(parent: HTMLElement, node: HTMLElement): HTMLElement {
  parent.appendChild(node);
  return node;
}
