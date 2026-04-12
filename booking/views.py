from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Car, Reservation
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login


def home(request):
    return render(request, "booking/home.html")

def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # 註冊完直接登入
            return redirect("/")
    else:
        form = UserCreationForm()

    return render(request, "booking/register.html", {"form": form})

@login_required
def reserve_car(request):
    cars = Car.objects.all()

    if request.method == "POST":
        car_id = request.POST.get("car")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        car = Car.objects.get(id=car_id)

        Reservation.objects.create(
            user=request.user,
            car=car,
            start_time=start_time,
            end_time=end_time
        )

        return redirect("reserve")

    return render(request, "booking/reserve.html", {"cars": cars})