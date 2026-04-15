import pygame

pygame.init()

W=800
H=480

screen=pygame.display.set_mode((W,H))

font_big=pygame.font.SysFont("arial",50)
font_mid=pygame.font.SysFont("arial",34)

mode="A1"


def bar(x,y,w,h,val):

    pygame.draw.rect(screen,(80,80,80),(x,y,w,h))
    pygame.draw.rect(screen,(0,180,0),(x,y,int(w*val),h))


def A1():

    t1=font_mid.render("TEMP 90C",True,(255,255,255))
    t2=font_mid.render("SPALANIE 7.5",True,(255,255,255))

    screen.blit(t1,(40,40))
    screen.blit(t2,(40,80))

    speed=font_big.render("95 km/h",True,(255,255,255))
    screen.blit(speed,(520,60))


def B2():

    txt=font_mid.render("ZASIEG",True,(255,255,255))
    screen.blit(txt,(350,200))

    bar(200,260,400,40,0.6)

    km=font_big.render("180 km",True,(255,255,255))
    screen.blit(km,(330,320))


running=True

while running:

    for e in pygame.event.get():

        if e.type==pygame.QUIT:
            running=False

        if e.type==pygame.KEYDOWN:
            if e.key==pygame.K_1:mode="A1"
            if e.key==pygame.K_2:mode="B2"

    screen.fill((0,0,0))

    if mode=="A1":
        A1()

    if mode=="B2":
        B2()

    pygame.display.flip()
