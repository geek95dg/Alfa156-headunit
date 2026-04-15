import pygame
import math

WIDTH = 800
HEIGHT = 480

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()

font_big = pygame.font.SysFont("arial", 48)
font_small = pygame.font.SysFont("arial", 26)

screen_mode = "A1"


def draw_gauge(cx, cy, radius, value, max_value, label):

    pygame.draw.circle(screen, (220,220,220), (cx,cy), radius)
    pygame.draw.circle(screen, (0,0,0), (cx,cy), radius,3)

    for i in range(0,11):
        angle = math.radians(210 - (i*24))
        x = cx + math.cos(angle)*(radius-10)
        y = cy - math.sin(angle)*(radius-10)

        x2 = cx + math.cos(angle)*(radius-2)
        y2 = cy - math.sin(angle)*(radius-2)

        pygame.draw.line(screen,(0,0,0),(x,y),(x2,y2),2)

    angle = math.radians(210 - (value/max_value)*240)

    nx = cx + math.cos(angle)*(radius-20)
    ny = cy - math.sin(angle)*(radius-20)

    pygame.draw.line(screen,(200,0,0),(cx,cy),(nx,ny),4)

    txt = font_small.render(label,True,(0,0,0))
    screen.blit(txt,(cx-40,cy+radius-30))


def screen_A1():

    draw_gauge(200,240,120,3500,7000,"RPM")
    draw_gauge(600,240,120,90,240,"KM/H")

    temp = font_big.render("90C",True,(255,255,255))
    fuel = font_big.render("7.5 L/100",True,(255,255,255))

    pygame.draw.rect(screen,(0,0,0),(320,180,160,120))

    screen.blit(temp,(350,185))
    screen.blit(fuel,(330,235))


def screen_A2():

    y=120
    lines=[
        "SREDNIE 7.5 L/100",
        "DOLOADOWANIE 1.2 BAR",
        "TRIP A 243 km"
    ]

    for l in lines:
        txt=font_big.render(l,True,(255,255,255))
        screen.blit(txt,(200,y))
        y+=80


def screen_B1():

    lines=[
        "15.03.2026   14:20",
        "TEMP ZEWN -2C",
        "UWAGA OBLODZENIE"
    ]

    y=120

    for l in lines:
        txt=font_big.render(l,True,(255,255,255))
        screen.blit(txt,(200,y))
        y+=80


def screen_B2():

    pygame.draw.rect(screen,(80,80,80),(150,200,500,60))

    pygame.draw.rect(screen,(200,200,0),(150,200,350,60))

    txt=font_big.render("ZASIEG 180km",True,(255,255,255))
    screen.blit(txt,(280,300))


def screen_C1():

    lines=[
        "DYSTANS 426 km",
        "CZAS 05:12",
        "SREDNIE 7.4 L"
    ]

    y=120
    for l in lines:
        txt=font_big.render(l,True,(255,255,255))
        screen.blit(txt,(200,y))
        y+=80


def screen_C2():

    lines=[
        "OLEJ OK",
        "OPONY OK",
        "PRZEGLAD 1200km"
    ]

    y=120
    for l in lines:
        txt=font_big.render(l,True,(255,255,255))
        screen.blit(txt,(200,y))
        y+=80


running=True

while running:

    for e in pygame.event.get():
        if e.type==pygame.QUIT:
            running=False

        if e.type==pygame.KEYDOWN:

            if e.key==pygame.K_1:
                screen_mode="A1"
            if e.key==pygame.K_2:
                screen_mode="A2"
            if e.key==pygame.K_3:
                screen_mode="B1"
            if e.key==pygame.K_4:
                screen_mode="B2"
            if e.key==pygame.K_5:
                screen_mode="C1"
            if e.key==pygame.K_6:
                screen_mode="C2"

    screen.fill((30,30,30))

    if screen_mode=="A1":
        screen_A1()

    if screen_mode=="A2":
        screen_A2()

    if screen_mode=="B1":
        screen_B1()

    if screen_mode=="B2":
        screen_B2()

    if screen_mode=="C1":
        screen_C1()

    if screen_mode=="C2":
        screen_C2()

    pygame.display.flip()
    clock.tick(30)
