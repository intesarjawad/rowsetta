import {
  CanvasTexture,
  LinearMipmapLinearFilter,
  Mesh,
  OrthographicCamera,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from 'three';

/**
 * The bevel of the loupe. Inside it the live vector map shows through,
 * enlarged evenly, so the middle stays a plain, legible magnified piece of the
 * map. The bevel is a thick rounded edge of clear glass: it shows the same
 * enlarged map, displaced outward more and more toward the rim, so every band
 * that reaches the edge bends and squeezes into it as it would at the edge of a
 * real lens. It reads at most 1.2 bevel widths outward and blurs as it goes,
 * so lines crowd softly rather than fan. A bright specular line runs along the
 * rim, strongest where it faces the light, with a fainter one opposite, and a
 * hairline ink edge holds it on a white page.
 */

const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

/** How much farther than its own place the bevel reads at the rim, in bevel widths. */
const REACH = 1.2;

const FRAGMENT = /* glsl */ `
uniform sampler2D uView;
uniform vec2 uViewSize;
uniform vec2 uHalf;
uniform float uRadius;
uniform float uBevel;
varying vec2 vUv;
uniform vec2 uCanvas;

float box(vec2 p) {
  vec2 q = abs(p) - uHalf + uRadius;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - uRadius;
}

void main() {
  vec2 p = (vUv - 0.5) * uCanvas;
  p.y = -p.y;
  float d = box(p);
  if (d > 0.0 || d < -uBevel) {
    gl_FragColor = vec4(0.0);
    return;
  }

  vec2 e = vec2(0.5, 0.0);
  vec2 n = normalize(vec2(box(p + e.xy) - box(p - e.xy), box(p + e.yx) - box(p - e.yx)) + 1e-5);
  // 0 where the bevel meets the flat middle, 1 at the rim.
  float t = 1.0 + d / uBevel;
  // The bevel's slope steepens toward the rim, so the map it shows is pushed
  // outward ever faster: lines bend into the edge and crowd together there.
  float push = ${REACH.toFixed(1)} * uBevel * t * t * t;
  vec2 q = p + n * push;
  // A little apart for red, green and blue, as thick glass splits light, and
  // softer toward the rim, so crowded lines blur together instead of fanning.
  vec2 spread = n * 1.2 * t * t;
  float soft = 2.5 * t * t;
  vec3 colour = vec3(
    texture2D(uView, (q + spread) / uViewSize + 0.5, soft).r,
    texture2D(uView, q / uViewSize + 0.5, soft).g,
    texture2D(uView, (q - spread) / uViewSize + 0.5, soft).b
  );

  // The curved face catches light on the lit side and falls into shade opposite.
  vec2 light = normalize(vec2(-0.55, -0.85));
  float facing = dot(n, light);
  colour = mix(colour, vec3(1.0), 0.28 * t * t * max(facing, 0.0));
  colour *= 1.0 - 0.18 * t * t * max(-facing, 0.0);
  // The specular rim: a bright line just inside the edge, brightest toward the light.
  float rim = smoothstep(-3.4, -2.2, d) * (1.0 - smoothstep(-1.6, -0.9, d));
  colour = mix(colour, vec3(1.0), rim * (0.55 + 0.45 * max(facing, 0.0)));
  // A hairline ink edge outside.
  colour = mix(colour, vec3(0.05), smoothstep(-0.9, -0.3, d));

  // The bevel fades in over its first pixels, so it meets the flat middle without a seam.
  float alpha = (1.0 - smoothstep(-0.3, 0.0, d)) * smoothstep(-uBevel, -uBevel + 2.0, d);
  gl_FragColor = vec4(clamp(colour, 0.0, 1.0) * alpha, alpha);
}
`;

export interface LensShape {
  /** The glass's half size and corner radius, in CSS pixels. */
  half: [number, number];
  radius: number;
  /** The width of the bevel; less than the corner radius, so its inner edge has no creases. */
  bevel: number;
  /** Room around the glass, so its edge is never clipped. */
  margin: number;
  magnify: number;
}

/** One stroke of a picture of the map, in map units. */
export interface Stroke {
  d: string;
  colour: string;
  width: number;
  opacity: number;
}

export interface Lens {
  /**
   * Paint the map enlarged `magnify` times about `focus`, which the glass
   * shows at its middle, and draw the bevel from it. The picture is painted
   * every call, so the bevel always shows the current map.
   */
  draw(
    focus: readonly [number, number],
    magnify: number,
    strokes: readonly Stroke[],
  ): void;
  dispose(): void;
}

export function createLens(
  canvas: HTMLCanvasElement,
  shape: LensShape,
  pixelRatio: number,
): Lens {
  const renderer = new WebGLRenderer({
    canvas,
    alpha: true,
    antialias: false,
    powerPreference: 'low-power',
  });
  const width = shape.half[0] * 2 + shape.margin * 2;
  const height = shape.half[1] * 2 + shape.margin * 2;
  renderer.setPixelRatio(pixelRatio);
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x000000, 0);

  // The enlarged map, reaching past the rim as far as the bevel reads.
  const reach = REACH * shape.bevel + 4;
  const view: [number, number] = [
    shape.half[0] * 2 + reach * 2,
    shape.half[1] * 2 + reach * 2,
  ];
  const paper = document.createElement('canvas');
  paper.width = Math.round(view[0] * pixelRatio);
  paper.height = Math.round(view[1] * pixelRatio);
  const ink = paper.getContext('2d');
  const texture = new CanvasTexture(paper);
  texture.flipY = false;
  texture.minFilter = LinearMipmapLinearFilter;

  const uniforms = {
    uView: { value: texture },
    uViewSize: { value: new Vector2(...view) },
    uCanvas: { value: new Vector2(width, height) },
    uHalf: { value: new Vector2(...shape.half) },
    uRadius: { value: shape.radius },
    uBevel: { value: shape.bevel },
  };
  const material = new ShaderMaterial({
    uniforms,
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    premultipliedAlpha: true,
    depthTest: false,
  });
  const scene = new Scene();
  const quad = new Mesh(new PlaneGeometry(2, 2), material);
  scene.add(quad);
  const camera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);
  let paths = new Map<string, Path2D>();

  return {
    draw(focus, magnify, strokes) {
      if (ink === null) return;
      const seen = new Map<string, Path2D>();
      const scale = magnify * pixelRatio;
      ink.setTransform(1, 0, 0, 1, 0, 0);
      ink.globalAlpha = 1;
      ink.fillStyle = '#ffffff';
      ink.fillRect(0, 0, paper.width, paper.height);
      ink.setTransform(
        scale,
        0,
        0,
        scale,
        paper.width / 2 - focus[0] * scale,
        paper.height / 2 - focus[1] * scale,
      );
      ink.lineJoin = 'round';
      for (const stroke of strokes) {
        const path = paths.get(stroke.d) ?? new Path2D(stroke.d);
        seen.set(stroke.d, path);
        ink.globalAlpha = stroke.opacity;
        ink.strokeStyle = stroke.colour;
        ink.lineWidth = stroke.width;
        ink.stroke(path);
      }
      paths = seen;
      texture.needsUpdate = true;
      renderer.render(scene, camera);
    },
    dispose() {
      texture.dispose();
      material.dispose();
      quad.geometry.dispose();
      renderer.dispose();
    },
  };
}
