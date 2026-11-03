"""モデルファイルを使わずに作るメッシュ（箱・円・マップ全体）。"""

import math

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomTrifans,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
)

from ..layout import LEVEL_BOUNDS, MAP_H, MAP_W
from ..theme import FLOOR_COLORS, SAFE_FLOOR_COLOR, WALL_COLOR, WALL_HEIGHT

# (法線, 4頂点) 立方体 (0,0,0)-(1,1,1)。反時計回りが表。
BOX_FACES = [
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
    ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
]


def make_unit_box():
    """モデルファイル不要の立方体（原点が角、一辺1）。"""
    vdata = GeomVertexData("box", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vdata.setNumRows(24)
    vertex = GeomVertexWriter(vdata, "vertex")
    normal = GeomVertexWriter(vdata, "normal")
    tris = GeomTriangles(Geom.UHStatic)
    for i, (face_normal, corners) in enumerate(BOX_FACES):
        for corner in corners:
            vertex.addData3(*corner)
            normal.addData3(*face_normal)
        tris.addVertices(i * 4, i * 4 + 1, i * 4 + 2)
        tris.addVertices(i * 4, i * 4 + 2, i * 4 + 3)
    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("box")
    node.addGeom(geom)
    return NodePath(node)

def make_disc(segments=32):
    """半径1の平らな円（音の広がりの表示用）。"""
    vdata = GeomVertexData("disc", GeomVertexFormat.getV3(), Geom.UHStatic)
    vdata.setNumRows(segments + 2)
    vertex = GeomVertexWriter(vdata, "vertex")
    vertex.addData3(0, 0, 0)
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        vertex.addData3(math.cos(angle), math.sin(angle), 0)
    fan = GeomTrifans(Geom.UHStatic)
    fan.addConsecutiveVertices(0, segments + 2)
    fan.closePrimitive()
    geom = Geom(vdata)
    geom.addPrimitive(fan)
    node = GeomNode("disc")
    node.addGeom(geom)
    return NodePath(node)


class MeshBuilder:
    """頂点色つきの四角形を1つのメッシュにまとめる（広いマップを軽く描くため）。"""

    def __init__(self):
        self.vdata = GeomVertexData("level", GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
        self.vertex = GeomVertexWriter(self.vdata, "vertex")
        self.normal = GeomVertexWriter(self.vdata, "normal")
        self.color = GeomVertexWriter(self.vdata, "color")
        self.tris = GeomTriangles(Geom.UHStatic)
        self.count = 0

    def add_quad(self, corners, face_normal, rgba):
        for corner in corners:
            self.vertex.addData3(*corner)
            self.normal.addData3(*face_normal)
            self.color.addData4(*rgba)
        base = self.count
        self.tris.addVertices(base, base + 1, base + 2)
        self.tris.addVertices(base, base + 2, base + 3)
        self.count += 4

    def build(self, name):
        geom = Geom(self.vdata)
        geom.addPrimitive(self.tris)
        node = GeomNode(name)
        node.addGeom(geom)
        return NodePath(node)


def add_wall_faces(builder, world, x, y):
    for face_normal, corners in BOX_FACES:
        nx, ny, nz = face_normal
        if nz < 0 or (nz == 0 and world.is_wall(x + nx, y + ny)):
            continue  # 底面と、隣が壁で見えない面は作らない
        points = [(x + u, y + v, w * WALL_HEIGHT) for u, v, w in corners]
        builder.add_quad(points, face_normal, WALL_COLOR)


def add_floor_face(builder, x, y, color):
    points = [(x, y, 0), (x + 1, y, 0), (x + 1, y + 1, 0), (x, y + 1, 0)]
    builder.add_quad(points, (0, 0, 1), color)


def touches_pocket(world, x, y):
    return any((x + dx, y + dy) in world.pocket for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def build_level_node(world):
    builder = MeshBuilder()
    x1, y1, x2, y2 = LEVEL_BOUNDS
    for y in range(y1, y2):
        for x in range(x1, x2):
            inside_map = 0 <= x < MAP_W and 0 <= y < MAP_H
            if not inside_map and (x, y) not in world.pocket and not touches_pocket(world, x, y):
                continue  # マップの外は、出っ張った小部屋とその壁だけ描く
            if world.is_wall(x, y):
                add_wall_faces(builder, world, x, y)
            elif (x, y) in world.safe_cells:
                add_floor_face(builder, x, y, SAFE_FLOOR_COLOR)
            else:
                add_floor_face(builder, x, y, FLOOR_COLORS[(x + y) % 2])
    return builder.build("level")
