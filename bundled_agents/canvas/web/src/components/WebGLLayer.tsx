import { useEffect, useRef } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { SceneVFX } from './SceneVFX'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'

export interface ViewState {
  offsetX: number
  offsetY: number
  zoom: number
  anchor: [number, number, number]
  domVisible: boolean
}

export interface WorldClick {
  x: number
  y: number
  z: number
}

interface WebGLLayerProps {
  vfxJs: string | null
  view: ViewState
  worldClick: WorldClick | null
}

const FOV = 50
const HALF_TAN = Math.tan((FOV / 2) * Math.PI / 180)  // ~0.466
const CAM_ELEV = 200  // elevation at zoom=1 — scales with dist to keep angle constant

// Perspective camera. DOM = camera. Slight elevation to see ground.
// Distance from screen plane computed so visible height ≈ DOM viewport height.
function CameraSync({ view }: { view: ViewState }) {
  const { camera, size } = useThree()
  const refDistRef = useRef(0)

  useFrame((state) => {
    const [ax, ay] = view.anchor
    const cx = ax + (size.width / 2 - view.offsetX) / view.zoom
    const cy = -(ay + (size.height / 2 - view.offsetY) / view.zoom)

    // Distance so that at Z=0 the visible height ≈ screen height / zoom
    const dist = size.height / (2 * view.zoom * HALF_TAN)

    // Reference distance at zoom=1 (for constant angle)
    if (!refDistRef.current) refDistRef.current = size.height / (2 * HALF_TAN)
    const elev = CAM_ELEV * dist / refDistRef.current

    camera.position.set(cx, cy + elev, dist)
    camera.lookAt(cx, cy, 0)
    camera.updateProjectionMatrix()
    state.invalidate()
  })

  return null
}

function WorldClickHandler({ worldClick }: { worldClick: WorldClick | null }) {
  const { scene, raycaster } = useThree()

  useFrame(() => {
    if (!worldClick) return
    raycaster.set(
      new THREE.Vector3(worldClick.x, worldClick.y, 500),
      new THREE.Vector3(0, 0, -1)
    )
    const intersects = raycaster.intersectObjects(scene.children, true)
    for (const hit of intersects) {
      const onClick = hit.object.userData?.onClick
      if (typeof onClick === 'function') {
        onClick(hit.point, hit.object)
        break
      }
    }
  })

  return null
}

// Restore alpha from RGB brightness — UnrealBloomPass destroys alpha
const AlphaRestoreShader = {
  uniforms: { tDiffuse: { value: null as THREE.Texture | null } },
  vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    varying vec2 vUv;
    void main() {
      vec4 c = texture2D(tDiffuse, vUv);
      float a = max(c.r, max(c.g, c.b));
      gl_FragColor = vec4(c.rgb, a);
    }
  `,
}

function PostProcessing() {
  const { gl, scene, camera, size } = useThree()
  const composerRef = useRef<EffectComposer | null>(null)

  useEffect(() => {
    const rt = new THREE.WebGLRenderTarget(size.width, size.height, {
      type: THREE.HalfFloatType,
    })
    const composer = new EffectComposer(gl, rt)
    composer.addPass(new RenderPass(scene, camera))
    const bloom = new UnrealBloomPass(
      new THREE.Vector2(size.width, size.height),
      0.5,   // strength
      0.6,   // radius
      0.8    // threshold
    )
    composer.addPass(bloom)
    const alphaPass = new ShaderPass(AlphaRestoreShader)
    composer.addPass(alphaPass)
    composerRef.current = composer
    return () => {
      composer.dispose()
      rt.dispose()
    }
  }, [gl, scene, camera])

  useEffect(() => {
    composerRef.current?.setSize(size.width, size.height)
  }, [size])

  useFrame(() => {
    composerRef.current?.render()
  }, 1)

  return null
}

export function WebGLLayer({ vfxJs, view, worldClick }: WebGLLayerProps) {
  return (
    <Canvas
      gl={{ alpha: true, antialias: true }}
      frameloop="demand"
      camera={{ fov: FOV, position: [0, CAM_ELEV, 1000], near: 1, far: 30000 }}
      style={{ position: 'absolute', inset: 0, zIndex: 0, pointerEvents: 'none' }}
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[500, 500, 500]} intensity={0.4} />
      <CameraSync view={view} />
      <WorldClickHandler worldClick={worldClick} />
      {vfxJs && <SceneVFX jsCode={vfxJs} />}
      <PostProcessing />
    </Canvas>
  )
}
