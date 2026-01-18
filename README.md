# HarborProject_CruzHacks26
## Inspiration
Santa Cruz is full of small businesses - but many of them operate on thin margins in a city where revenue, rent and foot traffic are constantly changing. Business owners don't fail because they lack the passion or skill to lead their business, but because they lack predictability and the ability to manage their finances due to volatility.
Harbor was inspired by a simple question:
*What if small businesses had an operating system that turned uncertainty into foresight - and preserved local businesses using Artificial Intelligence and Software?*

## What it does
Harbor is an operating system for local businesses that provides early warning, context, and tourism data based on a series of data plucked from public sources in Santa Cruz. It is combined into four integrated modules:
- **CashFlow Calm: **
Projects a certain number of days cash runway and translates raw financial data into clear states:
- Stable/Healthy
- Watch closely/Caution
- Action needed/Critical
It gives them actionable insight on what is needed to do. Instead of dashboards, it explains the risk = Revenue dip + fixed rent + possibly low tourism week = risk in profit and payroll. 

- **TouristPulse: **
Adds a 7 day prediction for businesses to operate using:
- Local events
- Weather conditions
- Tourism patterns using inbound traffic
This helps owners distinguish between what they need to do and when they need to set up shop/lock in.

- **Rent Guard:**
Our very own custom trained model was used for this feature. RentGuard demystifies rent by:
- Tracking rent increases over time
- Flagging aggresive hikes
- Providing recommended action to business owners
It doesn't give legal advice - but provides clarity to business owners.

- **Santa Cruz Shopline:**
Closes the loop by helping businesses stabilize demand, and monitor their competition. One of our most user-friendly features, as it allows for customers as well to connect with only *local* businesses in the area. 

*Together, Harbor turns isolated problems into a coherent system.*

## How we built it
We designed Harbor to be a hackathon-feasible project, but easily scalable.
Backend:
- FastAPI
- JWT Encryption
- Database on Superbase
- SQL Encryption hosted on Render

Frontend:
- HTML
- UI Inspired by Claude

Data approach:
- CSV uploads
- Publicly available data scrapped from Santa Cruz/Boardwalk sites.

We built all of this with one thing in the mind - to prioritize user friendliness and make sure owners have their businesses encrypted.

## Challenges we ran into
- Bugging and Debugging: One of our main issues was running into bugs when developing the code. We would debug the code and then run it through an AI model to make sure the code was running fine and we weren't struggling with constant issues.

- Server issues: One of our other main issues was dealing with a slow server on Render/constant server crashes. The server on Render was pretty slow, and took us time to fully test our product out.

## Accomplishments that we're proud of
- Built a unified model for small business predictability, while implementing large open source models like Deepseek and Gemini.
- Building our very own AI model trained from data collected by scraping rent and rent-increase on real-estate websites in Santa Cruz.
- Made something Santa Cruz-specific at first, but also made it adaptable so that it can be scaled to other cities where local businesses run the economy.

## What we learned
- Small business owners don't want analytics and looking at information they can't understand. Rather, they want clarity with their financials. This is the reason that Harbor exists and this is what we learned.
- We developed our soft skills, from Coding in Python, Building full stack applications and working with LLMs and small developed regression and classification models.

## What's next for Harbor: The operating system for local businesses
Short-term: 
- Expand our data sources (From POS to even possibly, Bank Integrations)
- Improve baselines by the business category.

Long-term vision:
- A trusted layer between small businesses, communities and customers.
- A system that helps local economies anticipate stress instead of instant failure.
- Can be monetized through subscriptions and bidding to be featured.

