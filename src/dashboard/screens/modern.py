import pygame

pygame.init()

W=800
H=480

screen=pygame.display.set_mode((W,H))
font_big=pygame.font.SysFont("arial",64)
font_mid=pygame.font.SysFont("arial",40)

mode="A1"

def A1():

    speed=font_big.render("95",True,(255,255,255))
    rpm=font_mid.render("RPM 3500",True,(180,180,180))
    fuel=font_mid.render("7.5 L/100",True,(180,180,180))

    screen.blit(speed,(350,160))
    screen.blit(rpm,(330,260))
    screen.blit(fuel,(330,310))


def list_screen(lines):

    y=120
    for l in lines:
        txt=font_mid.render(l,True,(255,255,255))
        screen.blit(txt,(200,y))
        y+=80


running=True

while running:

    for e in pygame.event.get():
        if e.type==pygame.QUIT:
            running=False

        if e.type==pygame.KEYDOWN:
            if e.key==pygame.K_1:mode="A1"
            if e.key==pygame.K_2:mode="A2"
            if e.key==pygame.K_3:mode="B1"
            if e.key==pygame.K_4:mode="B2"
            if e.key==pygame.K_5:mode="C1"
            if e.key==pygame.K_6:mode="C2"

    screen.fill((10,10,10))

    if mode=="A1":
        A1()

    if mode=="A2":
        list_screen(["SREDNIE 7.5","BOOST 1.2","TRIP 243km"])

    if mode=="B1":
        list_screen(["15.03 14:20","TEMP -2C","OBLODZENIE"])

    if mode=="B2":
        list_screen(["PALIWO 60%","ZASIEG 180km"])

    if mode=="C1":
        list_screen(["DYSTANS 426","CZAS 05:12","SREDNIE 7.4"])

    if mode=="C2":
        list_screen(["OLEJ OK","OPONY OK","SERWIS 1200km"])

    pygame.display.flip()
