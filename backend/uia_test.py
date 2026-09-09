import comtypes.client, comtypes, time, sys, traceback

try:
    UIAClient = comtypes.client.GetModule('UIAutomationCore.dll')
    uia = comtypes.client.CreateObject('{ff48dba4-60ef-4201-aa87-54103eef594e}', interface=UIAClient.IUIAutomation)
    root = uia.GetRootElement()
    
    cond = uia.CreatePropertyCondition(UIAClient.UIA_ClassNamePropertyId, 'Windows.UI.Core.CoreWindow')
    items = root.FindAll(UIAClient.TreeScope_Children, cond)
    with open('C:/Users/HONG/Desktop/uia_test.txt', 'w') as f:
        f.write(f'CoreWindow count: {items.Length}\n')
        for i in range(items.Length):
            el = items.GetElement(i)
            f.write(f'  {el.CurrentName} / {el.CurrentClassName}\n')
except Exception as e:
    with open('C:/Users/HONG/Desktop/uia_test.txt', 'w') as f:
        f.write(str(e) + '\n' + traceback.format_exc())
