# Finding the best player in European football

Trying to find the best player in Europe was a more difficult task than I initially envisioned when I began this process. On the surface it seems like a simple problem - who has the most goals and assists? Given that the the most difficult and important part of the game is scoring goals, we'll begin with that during the 2025 season while multiplying that with the [UEFA Coefficient](https://www.uefa.com/nationalassociations/uefarankings/) ([how it's calculated](https://en.wikipedia.org/wiki/UEFA_coefficient)). For those unfamiliar with the UEFA coefficient, it's essentially a measurement of strength of the league based on performance of European competitions (UEFA Champions League, UEFA Europa League, UEFA Conference League). For the model we will be grabbing the coefficient on a _by year_ basis. So for the 2025 season we will have to rerun the analysis every time a match is played in a European competition in that league.

For the top 5 leagues the ranking of players with most goals and assists is:
*INSERT DATAFRAME OF TOP 10 PLAYERS WITH PLAYER NAME/GOALS/ASSISTS/UEFA COEFFICIENT*

While we could stop there and hand the top player the ballon d'or, let's see if  advanced statistics can help find any new insights.

## Advanced Statistics

### Why use Advanced Statistics?

Before we delve into the details of how to use advanced statistics, let's discuss why they are important to help determine the best player in Europe:
* They can help quantify the "eye test". For those that watch soccer there's a visual element of a team dominating a game that doesn't always show up on the scoreboard, advanced statistics like expected goals are here to help quantify that.
* They can show how well a player is playing offensively even if it doesn't bare out in raw stats (goals and assists). For example, expected assists can show that a player is teeing their teammates up, but their teammates are wasteful in front of net.

### Problems with Advanced Statistics

It is important to note that there is some subjectivity to how these metrics are calculated. Since soccer is a dynamic sport there can be extrinsic factors that aren't accounted for when calculating something like expected goals (xG). xG is calculated by assigning a probability value to every shot based on thousands of shots of historical data from a similar spot. It does include distance to goal, shooting angle, body part, assist type and a couple more variables. The flaw with it is that it lacks contextual data like defensive pressure, game state, and an individual's finishing ability.

### Using Advanced Statistics on attacking players

To begin let's look at the xG to see which players should be getting the most goals.
*INSERT DATAFRAME WITH JUST PLAYER AND XG MULTIPLIED BY UEFA COEFFICIENT*

Now let's look at the most creative players in Europe, this will include expected assists (xA) and XGChain (Total xG of every possession the player is involved in) summed up. 
*INSERT DATAFRAME WITH PLAYER AND XA, XGCHAIN, XA+XGCHAIN MULTIPLIED BY UEFA COEFFICIENT*

And finally let's take a look at the highest combined score of both.
*INSERT DATAFRAME WITH PLAYER, XG, XA, XGCHAIN, XG+XA+XGCHAIN, MULTIPLIED BY UEFA COEFFICIENT*


### Creating a player efficiency rating for attacking

One of the most telling statistics in the NBA is the player efficiency rating (PER), this statistic summarizes a player's per minute statistical production to compare players influence on a game regardless of team's pace or minutes played. Since there is no way to calculate PER the same way since attacking is way less frequent in soccer than it is in basketball, we will find a way to calculate our own.

Some important things we will look at to determine a player's efficiency:
* What is the players xG to goals ratio, has the person vastly outperformed, underperformed, or hit their xG dead on?
* We will also be using the contribution to assisting goals that we've used above (xA + xGChain).
* Do we want to do per minute?
* Do we want to do percentage of goal contributions?


Sources
* Data from top 5 leagues: https://understat.com/
* Expected Goals: https://en.wikipedia.org/wiki/Expected_goals
* Expected Assists: https://theanalyst.com/articles/what-are-expected-assists-xa