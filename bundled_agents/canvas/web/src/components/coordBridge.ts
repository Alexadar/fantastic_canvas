// DOM canvas coords (same as agent x/y) <-> WebGL world coords
// Camera looks along -Z with Y-up (default THREE.js). DOM Y goes down, so we negate.
// Mapping: domX -> worldX, domY -> world -Y, depth -> worldZ

export function domToWorld(
  domX: number, domY: number,
  anchor: [number, number, number] = [0, 0, 0]
): [number, number, number] {
  return [anchor[0] + domX, -(anchor[1] + domY), anchor[2]]
}

export function worldToDom(
  wx: number, wy: number, _wz: number,
  anchor: [number, number, number] = [0, 0, 0]
): [number, number] {
  return [wx - anchor[0], -(wy + anchor[1])]
}

export function agentWorldBounds(
  agent: { x: number, y: number, width: number, height: number },
  anchor: [number, number, number] = [0, 0, 0]
) {
  return {
    center: domToWorld(agent.x + agent.width / 2, agent.y + agent.height / 2, anchor),
    size: [agent.width, agent.height] as [number, number],
  }
}
