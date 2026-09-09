from windows_toasts import InteractableWindowsToaster, Toast, ToastButton, ToastDisplayImage

# Initialize the toaster with a unique App ID
toaster = InteractableWindowsToaster('Python Script Notifier')

# Create the notification object with a long paragraph and image
new_toast = Toast([
    'Python Notification', 
    'Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
])

# Add an image (using a Windows default image)
try:
    new_toast.AddImage(ToastDisplayImage.fromPath('C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg'))
except:
    print("Could not load image")

# Show the notification
toaster.show_toast(new_toast)
