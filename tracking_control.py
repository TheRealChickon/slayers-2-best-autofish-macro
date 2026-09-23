"""Screen-space reel control with braking learned from observed marker motion."""
import math


def clamp(value, low, high):
    return max(low,min(high,value))


class ReelMotion:
    def __init__(self):
        self.up_accel=self.down_accel=1240.
        self.suspend()

    def suspend(self):
        self.previous=None
        self.velocity=self.target_velocity=0.
        self.held=False
        self.changed_at=0.
        self.rejected=0

    def step(self, detection, now):
        ball,target=detection['ball'],detection['target']
        if self.previous is not None:
            dt=now-self.previous[0]
            if dt<=0:return self.held
            if dt>.15:
                self.previous=None;self.velocity=self.target_velocity=0.
            elif abs(ball-self.previous[1])>max(35,800*dt):
                # One impossible marker jump must not reverse the reel.
                self.rejected+=1
                if self.rejected>=2:self.suspend()
                return self.held
        if self.previous is not None:
            dt=max(.005,now-self.previous[0])
            old_velocity=self.velocity
            alpha=1-math.exp(-dt/.025)
            self.velocity+=alpha*((ball-self.previous[1])/dt-self.velocity)
            target_delta=target-self.previous[2]
            if abs(target_delta)>max(60,1000*dt):
                self.target_velocity=0.
            else:
                self.target_velocity+=(1-math.exp(-dt/.035))*(clamp(target_delta/dt,-500,500)-self.target_velocity)
            # Ignore switches, boundaries and implausible acceleration samples.
            observed=(self.velocity-old_velocity)/dt+4.2*self.velocity
            signed=-observed if self.held else observed
            if now-self.changed_at>.08 and 70<ball<510 and 400<signed<3000:
                amount=1-math.exp(-dt/.8)
                if self.held:self.up_accel+=amount*(signed-self.up_accel)
                else:self.down_accel+=amount*(signed-self.down_accel)
        self.rejected=0
        relative=self.velocity-self.target_velocity
        braking=(self.up_accel+4.2*self.velocity if relative>=0 else self.down_accel-4.2*self.velocity)
        braking=max(400,braking)
        # Time to brake depends on the rod's observed response and direction,
        # rather than one fixed prediction multiplier for every rod.
        error=ball-target+.07*relative+relative*abs(relative)/(2*braking)
        margin=max(0,(detection.get('height',54)-detection.get('ball_height',31))/2)
        deadband=clamp(margin*.15,1.25,3.)
        was_held=self.held
        if error>deadband:self.held=True
        elif error<-deadband:self.held=False
        if was_held!=self.held:self.changed_at=now
        self.previous=(now,ball,target)
        return self.held
