/* Convoy character viewer.
 *
 * The point of this page is to settle one question with a real render rather
 * than an argument: does a 3D model under an ORTHOGRAPHIC camera at a fixed
 * angle read as 2D? The camera toggle is there so the two can be compared
 * back to back on the same asset.
 *
 * It is also the seed of the real viewer. The map scene in PHASE5 step 4 is
 * this plus terrain, buildings, and agent positions driven by the track data
 * render_world.py already reconstructs.
 */
import React, { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import {
  useGLTF, useAnimations, OrthographicCamera, PerspectiveCamera,
  ContactShadows, Grid, OrbitControls,
} from '@react-three/drei'

const MODEL = '/models/dwarf.glb'

/* Camera sits south of the subject and looks slightly down. 20 degrees is
 * between the 10 used for character sprites and the 48 used for buildings --
 * high enough to read the ground plane, low enough to keep faces visible. */
const ELEVATION_DEG = 20
const AZIMUTH_DEG = 0

function cameraPosition(distance) {
  const e = (ELEVATION_DEG * Math.PI) / 180
  const a = (AZIMUTH_DEG * Math.PI) / 180
  return [
    distance * Math.cos(e) * Math.sin(a),
    distance * Math.sin(e),
    distance * Math.cos(e) * Math.cos(a),
  ]
}

function Character({ clip, walking, spin }) {
  const group = useRef()
  const { scene, animations } = useGLTF(MODEL)
  const { actions } = useAnimations(animations, group)

  /* Clone so the same GLB can be instanced many times later without the
   * copies sharing (and fighting over) one skeleton. */
  const model = useMemo(() => scene.clone(true), [scene])

  useEffect(() => {
    const action = actions[clip]
    if (!action) return
    action.reset().fadeIn(0.25).play()
    return () => action.fadeOut(0.25)
  }, [actions, clip])

  /* Walking in place looks wrong, so the model actually travels and loops --
   * the same thing the map will do between two locations. */
  useFrame((state, delta) => {
    if (!group.current) return
    if (spin) group.current.rotation.y += delta * 0.6
    if (walking) {
      group.current.position.x += delta * 0.55
      if (group.current.position.x > 2.2) group.current.position.x = -2.2
    } else {
      group.current.position.x = 0
    }
  })

  return <group ref={group}><primitive object={model} /></group>
}

function Scene({ ortho, clip, walking, spin, zoom }) {
  return (
    <>
      {ortho ? (
        <OrthographicCamera makeDefault position={cameraPosition(20)} zoom={zoom} near={-50} far={100} />
      ) : (
        <PerspectiveCamera makeDefault position={cameraPosition(4.6)} fov={35} />
      )}
      <OrbitControls target={[0, 0.85, 0]} enablePan={false} minDistance={2} maxDistance={12} />

      {/* Explicit lights only. `Environment preset` fetches an HDRI from a CDN,
        * which popped in a second after load and visibly changed the render --
        * and would simply fail on a locked-down school network. Three lights
        * cost nothing and are deterministic: key from the front-right so faces
        * are lit toward the camera, fill opposite, and a soft ambient floor so
        * nothing goes black. */}
      <ambientLight intensity={1.1} />
      <directionalLight position={[3, 6, 6]} intensity={2.0} castShadow
                        shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-4, 3, -2]} intensity={0.7} />
      <hemisphereLight args={['#eaf4ec', '#7d9a86', 0.6]} />

      <Suspense fallback={null}>
        <Character clip={clip} walking={walking} spin={spin} />
      </Suspense>

      <ContactShadows position={[0, 0.01, 0]} opacity={0.45} scale={12} blur={2.2} far={4} />
      {/* A finite grid rather than `infiniteGrid`, which fades against an
        * orthographic camera and disappeared entirely at some zoom levels. */}
      <Grid
        position={[0, 0, 0]} args={[30, 30]} cellSize={0.5} cellThickness={0.7}
        sectionSize={2.5} sectionThickness={1.2}
        cellColor="#bcd6c5" sectionColor="#8fbfa2" fadeStrength={1} fadeDistance={60}
      />
    </>
  )
}

const CLIPS = [
  ['Walking', 'walk — travelling the road'],
  ['Heavy_Hammer_Swing', 'hammer — working a shift'],
  ['Running', 'run'],
  ['RunFast', 'run fast'],
  ['air_squat', 'squat'],
  ['360_Power_Spin_Jump', 'spin jump'],
]

export default function App() {
  const [ortho, setOrtho] = useState(true)
  const [clip, setClip] = useState('Walking')
  const [walking, setWalking] = useState(true)
  const [spin, setSpin] = useState(false)
  const [zoom, setZoom] = useState(150)

  const btn = (on) => ({
    font: 'inherit', padding: '6px 12px', borderRadius: 7, cursor: 'pointer',
    border: `1px solid ${on ? '#1b914d' : '#c9d8cf'}`,
    background: on ? '#1b914d' : '#fff', color: on ? '#fff' : '#1d2b24',
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <header style={{
        padding: '12px 18px', background: '#fff', borderBottom: '1px solid #c9d8cf',
        display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap',
      }}>
        <strong style={{ letterSpacing: '.02em' }}>Convoy — character viewer</strong>
        <span style={{ color: '#5d6f66', fontSize: 12 }}>dwarf.glb · 947 KB · 7 clips</span>

        <div style={{ display: 'flex', gap: 8 }}>
          <button style={btn(ortho)} onClick={() => setOrtho(true)}>Orthographic</button>
          <button style={btn(!ortho)} onClick={() => setOrtho(false)}>Perspective</button>
        </div>

        <select value={clip} onChange={(e) => setClip(e.target.value)}
                style={{ font: 'inherit', padding: '6px 10px', borderRadius: 7,
                         border: '1px solid #c9d8cf', background: '#fff' }}>
          {CLIPS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>

        <button style={btn(walking)} onClick={() => setWalking(!walking)}>
          {walking ? 'Travelling' : 'In place'}
        </button>
        <button style={btn(spin)} onClick={() => setSpin(!spin)}>
          {spin ? 'Turning' : 'Facing you'}
        </button>

        {ortho && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: '#5d6f66' }}>
            zoom
            <input type="range" min="60" max="320" value={zoom}
                   onChange={(e) => setZoom(+e.target.value)} style={{ accentColor: '#1b914d' }} />
          </label>
        )}
      </header>

      <div style={{ flex: 1, minHeight: 0 }}>
        <Canvas shadows dpr={[1, 2]} style={{ background: '#eef4ef' }}>
          <Scene ortho={ortho} clip={clip} walking={walking} spin={spin} zoom={zoom} />
        </Canvas>
      </div>

      <footer style={{
        padding: '10px 18px', background: '#fff', borderTop: '1px solid #c9d8cf',
        color: '#5d6f66', fontSize: 12.5,
      }}>
        <strong style={{ color: '#1d2b24' }}>Orthographic</strong> is the flat, map-like
        look — parallel lines stay parallel, so the model reads as 2D art even though it is
        a live 3D mesh playing a real animation. <strong style={{ color: '#1d2b24' }}>Perspective</strong> is
        the same asset with depth. Drag to orbit; the model keeps animating either way.
      </footer>
    </div>
  )
}

useGLTF.preload(MODEL)
