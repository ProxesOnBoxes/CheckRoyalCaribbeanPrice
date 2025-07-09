import requests
import yaml
from apprise import Apprise
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import re
import base64
import json


appKey = "hyNNqIPHHzaLzVpcICPdAdbFV8yvTsAm"
cruiseLineName = ""
already_checked_items = {}
reservation_friendly_names = {}

def main():
    global reservation_friendly_names

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(timestamp)
    
    apobj = Apprise()
        
    with open('config.yaml', 'r') as file:
        data = yaml.safe_load(file)
        
        if 'apprise' in data:
            for apprise in data['apprise']:
                url = apprise['url']
                apobj.add(url)

        if 'apprise_test' in data and data['apprise_test']:
            apobj.notify(body="This is only a test. Apprise is set up correctly", title='Cruise Price Notification Test')
            print("Apprise Notification Sent...quitting")
            quit()

        # Support for additional orders to check
        if 'reservation_friendly_names' in data:
            reservation_friendly_names = data['reservation_friendly_names']
        
        if 'accountInfo' in data:
            for accountInfo in data['accountInfo']:
                username = accountInfo['username']
                password = accountInfo['password']
                if 'cruiseLine' in accountInfo:
                   if accountInfo['cruiseLine'].lower().startswith("c"):
                    cruiseLineName = "celebritycruises"
                   else:
                    cruiseLineName =  "royalcaribbean"
                else:
                   cruiseLineName =  "royalcaribbean"     
                    
                print(cruiseLineName + " " + username)
                session = requests.session()
                access_token,accountId,session = login(username,password,session,cruiseLineName)
                getLoyalty(access_token,accountId,session)
                getVoyages(access_token,accountId,session,apobj,cruiseLineName)
    
        if 'cruises' in data:
            for cruises in data['cruises']:
                cruiseURL = cruises['cruiseURL'] 
                paidPrice = float(cruises['paidPrice'])
                get_cruise_price(cruiseURL, paidPrice, apobj)

        if 'additional_orders' in data:
            # Use the last set of access_token, accountId, session, cruiseLineName from accountInfo
            for order in data['additional_orders']:
                reservationId = order['reservationId']
                ship = order['ship']
                startDate = order['startDate']
                prefix = order['prefix']
                paidPrice = float(order['paidPrice'])
                product = order['product']
                # apobj and session/account info already set from previous login
                try:
                    getNewBeveragePrice(access_token, accountId, session, reservationId, ship, startDate, prefix, paidPrice, product, apobj, is_additional_order=True)
                except Exception as e:
                    print(f"Error checking additional order {getFriendlyName(reservationId)} - {reservationId}: {e}")
            
def login(username,password,session,cruiseLineName):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': 'Basic ZzlTMDIzdDc0NDczWlVrOTA5Rk42OEYwYjRONjdQU09oOTJvMDR2TDBCUjY1MzdwSTJ5Mmg5NE02QmJVN0Q2SjpXNjY4NDZrUFF2MTc1MDk3NW9vZEg1TTh6QzZUYTdtMzBrSDJRNzhsMldtVTUwRkNncXBQMTN3NzczNzdrN0lC',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
    }
    
    data = 'grant_type=password&username=' + username +  '&password=' + password + '&scope=openid+profile+email+vdsid'
    
    response = session.post('https://www.'+cruiseLineName+'.com/auth/oauth2/access_token', headers=headers, data=data)
    
    if response.status_code != 200:
        print(cruiseLineName + " Website Might Be Down. Quitting")
        quit()
          
    access_token = response.json().get("access_token")
    
    list_of_strings = access_token.split(".")
    string1 = list_of_strings[1]
    decoded_bytes = base64.b64decode(string1 + '==')
    auth_info = json.loads(decoded_bytes.decode('utf-8'))
    accountId = auth_info["sub"]
    return access_token,accountId,session

def getFriendlyName(reservationId):
    """
    @param reservationId: The reservation ID to look up as a string.
    @returns a friendly name for the reservationId if it exists in the mapping, otherwise an empty string.
    @brief Returns a friendly name for the reservationId if it exists in the mapping.
    """

    global reservation_friendly_names
    if reservationId and str(reservationId) in reservation_friendly_names:
        return reservation_friendly_names[str(reservationId)]
    return ""

def getNewBeveragePrice(access_token,accountId,session,reservationId,ship,startDate,prefix,paidPrice,product,apobj, is_additional_order=False, number_of_devices=1):
    global already_checked_items
    global reservation_friendly_names
    friendly_cruise_name = getFriendlyName(reservationId)

    # Check if the item has already been checked
    item_key = f"{ship}_{startDate}_{prefix}_{product}"
    if item_key in already_checked_items:
        print(friendly_cruise_name + f": Skipping already checked item: {already_checked_items[item_key]}")
        return

    headers = {
        'Access-Token': access_token,
        'AppKey': appKey,
        'vds-id': accountId,
    }

    params = {
        'startDate': startDate,
        'currencyIso': 'USD',
    }
    if reservationId:
        params['reservationId'] = reservationId

    response = session.get(
        'https://aws-prd.api.rccl.com/en/royal/web/commerce-api/catalog/v2/' + ship + '/categories/' + prefix + '/products/' + str(product),
        params=params,
        headers=headers,
    )
    
    addon_name = response.json().get("payload").get("title")

    already_checked_items[item_key] = addon_name  # Mark this item as checked

    name_and_reservation = friendly_cruise_name + " (" + reservationId + "): "

    try:
        newPricePayload = response.json().get("payload").get("startingFromPrice")
    except:
        print(name_and_reservation + addon_name + " is No Longer For Sale")
        return
        
    currentPrice = get_current_price(prefix, number_of_devices, newPricePayload)

    # TODO: Update remove this and/or update the generic addon logic once internet packages support is fully implemented
    if (prefix == "pt_internet") and (number_of_devices > 1):
        email_title = "Cruise Addon Price Manual Check"
        if friendly_cruise_name:
            email_title += " for " + friendly_cruise_name
        email_body = name_and_reservation + "Cruise Addon Price for Internet Package is not fully implemented yet for multiple devices. Please check manually, but current price for one device is " + str(currentPrice) + "."
        email_body += "\n\n"
        email_body += "The price for multiple devices can be found at:\n"
        email_body += "https://www.royalcaribbean.com/account/cruise-planner/category/"+prefix+"/product/"+str(product)+"?bookingId="+reservationId+"&shipCode="+ship+"&sailDate="+startDate

        apobj.notify(body=email_body, title=email_title)
        print(email_body)
        return

    if currentPrice < paidPrice:
        email_title = "Cruise Addon Price Alert"
        email_body = ""
        if is_additional_order:
            email_title += " For Watched Item"

        # Try to get a friendly name from the mapping if reservationId is set
        if friendly_cruise_name:
            email_title += " for " + friendly_cruise_name

        if is_additional_order:
            email_body += name_and_reservation + "Watched item " + addon_name + " Price is lower: " + str(currentPrice) + " than " + str(paidPrice)
        else:
            email_body += name_and_reservation + "Rebook! " + addon_name + " Price is lower: " + str(currentPrice) + " than " + str(paidPrice)

        web_url = "https://www.royalcaribbean.com/account/cruise-planner/category/"+prefix+"/product/"+str(product)+"?bookingId="+reservationId+"&shipCode="+ship+"&sailDate="+startDate

        email_body += " " + web_url
        print(email_body)
        apobj.notify(body=email_body, title=email_title)
    else:
        print(name_and_reservation + "You have the best price for " + addon_name +  " of: " + str(paidPrice))
        
    if currentPrice > paidPrice:
        print(name_and_reservation + "\t " + "Price of " + addon_name + " is now higher: " + str(currentPrice))

def get_current_price(prefix, number_of_devices, newPricePayload):
    """
    Currently this is mostly just a placeholder function, as the logic for correctly handling multiple devices
    for internet packages is not fully implemented yet.

    @brief Returns the current price based on the prefix and newPricePayload.
    @param prefix: The prefix of the product type (e.g., beverage, internet).
    @param number_of_devices: The number of devices for internet packages.
    @param newPricePayload: The payload containing price information.
    @returns: The current price as a float.
    """
    currentPrice = newPricePayload.get("adultPromotionalPrice")
    
    if not currentPrice:
        currentPrice = newPricePayload.get("adultShipboardPrice")
    return currentPrice

def getLoyalty(access_token,accountId,session):

    headers = {
        'Access-Token': access_token,
        'AppKey': appKey,
        'account-id': accountId,
    }
    response = session.get('https://aws-prd.api.rccl.com/en/royal/web/v1/guestAccounts/loyalty/info', headers=headers)
    loyalty = response.json().get("payload").get("loyaltyInformation")
    cAndANumber = loyalty.get("crownAndAnchorId")
    cAndALevel = loyalty.get("crownAndAnchorSocietyLoyaltyTier")
    cAndAPoints = loyalty.get("crownAndAnchorSocietyLoyaltyIndividualPoints")
    print("C&A: " + str(cAndANumber) + " " + cAndALevel + " " + str(cAndAPoints) + " Points")  
    
    
def getVoyages(access_token,accountId,session,apobj,cruiseLineName):

    headers = {
        'Access-Token': access_token,
        'AppKey': appKey,
        'vds-id': accountId,
    }
    
    if cruiseLineName == "royalcaribbean":
        brandCode = "R"
    else:
        brandCode = "C"
        
    params = {
        'brand': brandCode,
        'includeCheckin': 'false',
    }

    response = requests.get(
        'https://aws-prd.api.rccl.com/v1/profileBookings/enriched/' + accountId,
        params=params,
        headers=headers,
    )

    for booking in response.json().get("payload").get("profileBookings"):
        reservationId = booking.get("bookingId")
        passengerId = booking.get("passengerId")
        sailDate = booking.get("sailDate")
        numberOfNights = booking.get("numberOfNights")
        shipCode = booking.get("shipCode")
        
        name_and_reservation = getFriendlyName(str(reservationId)) + "(" + reservationId + "): "

        print(name_and_reservation + sailDate + " " + shipCode + " Room " + booking.get("stateroomNumber"))
        if booking.get("balanceDue") is True:
            print(name_and_reservation + "Remaining Cruise Payment Balance is $" + str(booking.get("balanceDueAmount")))
            
        getOrders(access_token,accountId,session,reservationId,passengerId,shipCode,sailDate,numberOfNights,apobj)
    
def getRoyalUp(access_token,accountId,session,apobj):
    # Unused, need javascript parsing to see offer
    # Could notify when Royal Up is available, but not too useful.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.5',
        # 'Accept-Encoding': 'gzip, deflate, br, zstd',
        'X-Requested-With': 'XMLHttpRequest',
        'AppKey': 'hyNNqIPHHzaLzVpcICPdAdbFV8yvTsAm',
        'Access-Token': access_token,
        'vds-id': accountId,
        'Account-Id': accountId,
        'X-Request-Id': '67e0a0c8e15b1c327581b154',
        'Req-App-Id': 'Royal.Web.PlanMyCruise',
        'Req-App-Vers': '1.73.0',
        'Content-Type': 'application/json',
        'Origin': 'https://www.'+cruiseLineName+'.com',
        'DNT': '1',
        'Sec-GPC': '1',
        'Connection': 'keep-alive',
        'Referer': 'https://www.'+cruiseLineName+'.com/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'Priority': 'u=0',
        # Requests doesn't support trailers
        # 'TE': 'trailers',
    }
    
    
    response = requests.get('https://aws-prd.api.rccl.com/en/royal/web/v1/guestAccounts/upgrades', headers=headers)
    for booking in response.json().get("payload"):
        print( booking.get("bookingId") + " " + booking.get("offerUrl") )
    
def getOrders(access_token,accountId,session,reservationId,passengerId,ship,startDate,numberOfNights,apobj):
    
    headers = {
        'Access-Token': access_token,
        'AppKey': appKey,
        'Account-Id': accountId,
    }
    
    params = {
        'passengerId': passengerId,
        'reservationId': reservationId,
        'sailingId': ship + startDate,
        'currencyIso': 'USD',
        'includeMedia': 'false',
    }
    
    response = requests.get(
        'https://aws-prd.api.rccl.com/en/royal/web/commerce-api/calendar/v1/' + ship + '/orderHistory',
        params=params,
        headers=headers,
    )
 
    # Check for my orders and orders others booked for me
    for order in response.json().get("payload").get("myOrders") + response.json().get("payload").get("ordersOthersHaveBookedForMe"):
        orderCode = order.get("orderCode")
        
        # Only get Valid Orders That Cost Money
        if order.get("orderTotals").get("total") > 0: 
            
            # Get Order Details
            response = requests.get(
                'https://aws-prd.api.rccl.com/en/royal/web/commerce-api/calendar/v1/' + ship + '/orderHistory/' + orderCode,
                params=params,
                headers=headers,
            )
            
            number_of_devices = 1  # This is only used for internet packages, default to 1 device
            for orderDetail in response.json().get("payload").get("orderHistoryDetailItems"):
                # check for cancelled status at item-level
                if orderDetail.get("guests")[0].get("orderStatus") == "CANCELLED":
                    continue
                order_title = orderDetail.get("productSummary").get("title")
                product = orderDetail.get("productSummary").get("id")
                prefix = orderDetail.get("productSummary").get("productTypeCategory").get("id")
                paidPrice = orderDetail.get("guests")[0].get("priceDetails").get("subtotal")
                if paidPrice == 0:
                    continue
                # These packages report total price, must divide by number of days
                if prefix == "pt_beverage":
                      if not order_title.startswith("Evian") and not order_title.startswith("Specialty Coffee"):
                          paidPrice = round(paidPrice / numberOfNights,2)
                if prefix == "pt_internet":
                    # TODO: very quick and dirty fix, to handle my current situation may break for others
                    number_of_devices = int(orderDetail.get("guests")[0].get("promoDescription").get("code").split('33S')[1][0])
                    paidPrice = round(paidPrice / number_of_devices / numberOfNights, 2)

                getNewBeveragePrice(access_token,accountId,session,reservationId,ship,startDate,prefix,paidPrice,product,apobj, number_of_devices=number_of_devices)

def get_cruise_price(url, paidPrice, apobj):
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    }

    # clean url of r0y and r0x tags
    findindex1=url.find("r0y")
    findindex2=url.find("&",findindex1+1)
    if findindex2==-1:
        url=url[0:findindex1-1]
    else:
        url=url[0:findindex1-1]+url[findindex2:len(url)]
    
    findindex1=url.find("r0x")
    findindex2=url.find("&",findindex1+1)
    if findindex2==-1:
        url=url[0:findindex1-1]
    else:
        url=url[0:findindex1-1]+url[findindex2:len(url)]
        
    
    
    m = re.search('www.(.*).com', url)
    cruiseLineName = m.group(1)
    parsed_url = urlparse(url)
    params = parse_qs(parsed_url.query)
    
    response = requests.get('https://www.'+cruiseLineName+'.com/checkout/guest-info', params=params,headers=headers)
    
    preString = params.get("sailDate")[0] + " " + params.get("shipCode")[0]+ " " + params.get("cabinClassType")[0] + " " + params.get("r0f")[0]
    
    roomNumberList = params.get("r0j")
    if roomNumberList:
        roomNumber = roomNumberList[0]
        preString = preString + " Cabin " + roomNumber
    
    soup = BeautifulSoup(response.text, "html.parser")
    soupFind = soup.find("span",attrs={"class":"SummaryPrice_title__1nizh9x5","data-testid":"pricing-total"})
    if soupFind is None:
        m = re.search("\"B:0\",\"NEXT_REDIRECT;replace;(.*);307;", response.text)
        if m is not None:
            redirectString = m.group(1)
            textString = preString + ": URL Not Working - Redirecting to suggested room"
            print(textString)
            newURL = "https://www." + cruiseLineName + ".com" + redirectString
            get_cruise_price(newURL, paidPrice, apobj)
            print("Update url to: " + newURL)
            return
        else:
            textString = preString + " No Longer Available To Book"
            print(textString)
            apobj.notify(body=textString, title='Cruise Room Not Available')
            return
    
    priceString = soupFind.text
    priceString = priceString.replace(",", "")
    m = re.search("\\$(.*)USD", priceString)
    priceOnlyString = m.group(1)
    price = float(priceOnlyString)
    
    if price < paidPrice: 
        textString = "Rebook! " + preString + " New Price of "  + str(price) + " is lower than " + str(paidPrice)
        print(textString)
        apobj.notify(body=textString, title='Cruise Price Alert')
    else:
        print(preString + ": You have best Price of " + str(paidPrice) )
        if price > paidPrice:
            print("\t Current Price is higher: " + str(price) )

if __name__ == "__main__":
    main()
 
