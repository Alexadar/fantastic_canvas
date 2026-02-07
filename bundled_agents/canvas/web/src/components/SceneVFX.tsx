import { useEffect, useRef } from 'react'
import { useThree, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

/**
 * Executes arbitrary JS code in the 3D scene context.
 *
 * The code receives: scene, THREE, camera, renderer, clock
 * It can return a cleanup function and/or set `this.onFrame(delta, elapsed)`.
 *
 * Example code:
 *   const geo = new THREE.TorusKnotGeometry(20, 6, 64, 16)
 *   const mat = new THREE.MeshStandardMaterial({ color: '#ff4488', wireframe: true })
 *   const mesh = new THREE.Mesh(geo, mat)
 *   mesh.position.set(0, 100, 0)
 *   scene.add(mesh)
 *   this.onFrame = (dt, t) => { mesh.rotation.y += 0.01 }
 *   return () => { scene.remove(mesh); geo.dispose(); mat.dispose() }
 */

interface SceneVFXProps {
  jsCode: string
}

export function SceneVFX({ jsCode }: SceneVFXProps) {
  const { scene, camera, gl, clock } = useThree()
  const onFrameRef = useRef<((delta: number, elapsed: number) => void) | null>(null)
  const cleanupRef = useRef<(() => void) | null>(null)
  const ctxRef = useRef<{ onFrame: ((delta: number, elapsed: number) => void) | null } | null>(null)
  const accumRef = useRef(0)

  useEffect(() => {
    if (!jsCode) return

    // Clean previous
    if (cleanupRef.current) {
      cleanupRef.current()
      cleanupRef.current = null
    }
    onFrameRef.current = null

    const ctx: { onFrame: ((delta: number, elapsed: number) => void) | null } = { onFrame: null }
    ctxRef.current = ctx

    try {
      const fn = new Function('scene', 'THREE', 'camera', 'renderer', 'clock', jsCode)
      const result = fn.call(ctx, scene, THREE, camera, gl, clock)
      if (typeof result === 'function') {
        cleanupRef.current = result
      }
      if (ctx.onFrame) {
        onFrameRef.current = ctx.onFrame
      }
    } catch (e) {
      console.error('SceneVFX error:', e)
    }

    return () => {
      if (cleanupRef.current) {
        cleanupRef.current()
        cleanupRef.current = null
      }
      onFrameRef.current = null
    }
  }, [jsCode, scene, camera, gl, clock])

  useFrame((state, delta) => {
    // Check for async onFrame assignment (e.g. after fetch)
    if (!onFrameRef.current && ctxRef.current?.onFrame) {
      onFrameRef.current = ctxRef.current.onFrame
    }
    if (onFrameRef.current) {
      accumRef.current += delta
      if (accumRef.current < 0.05) return  // ~20fps cap
      accumRef.current = 0
      onFrameRef.current(delta, clock.getElapsedTime())
      state.invalidate()
    }
  })

  return null
}
