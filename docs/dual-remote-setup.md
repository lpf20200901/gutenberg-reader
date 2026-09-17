# 双远端发布：GitHub 为主，Gitee 为镜像

同一份代码同时放在 GitHub 和 Gitee 上，**本地只保留一份仓库**，靠"多个远端"实现。
这份文档记录配置方式和三个真实踩到的平台差异。

---

## 为什么不是两份仓库

远端（remote）本质上只是"这个仓库的副本放在哪儿"的地址，**跟内容、身份、历史都无关**。

同一个人用不同的邮箱注册了两个平台，也**不需要两份本地仓库**——因为作者信息是在
**创建 commit 的那一刻**写进 commit 对象里的，之后永远跟着这个 commit 走，
跟它被推到哪里没关系。

一个附带的好处：同一批 commit 推到两个平台，**SHA 完全一致**（SHA 是内容寻址的）。
这可以直接用来验证两边是不是同一份历史。

---

## 配置

```bash
# origin 指向主仓库，这是 git 惯例
git remote add origin git@github.com:<user>/<repo>.git

# 镜像用独立名字，语义明确
git remote add gitee  git@gitee.com:<user>/<repo>.git

# 让本地分支默认跟踪主仓库
git branch --set-upstream-to=origin/master master
```

之后：

```bash
git push              # 推到主仓库（origin）
git push gitee master # 同步镜像
```

### 一条命令推两边（可选）

```bash
git remote set-url --add --push origin git@github.com:<user>/<repo>.git
git remote set-url --add --push origin git@gitee.com:<user>/<repo>.git
```

代价是失败时分不清是哪个远端出的问题。**明确写两条命令更好排查**，这个技巧按需用。

---

## 邮箱归属：真正的坑在这里

**commit 是否关联到你的账号，只取决于 commit 里的邮箱是否注册在该账号下**，
跟仓库所有者是谁无关。

如果不匹配，commit 在项目页上会显示成一个**点不进去的陌生作者**，而且
**不会计入你的贡献图**。对一个作品集来说这个损失挺大。

### 本次实际经历的三个阶段

| 阶段 | commit 邮箱 | 结果 |
| --- | --- | --- |
| 1 | 账号 A 的邮箱 | ✅ 关联，但关联到的是**另一个账号**（仓库所有者是账号 B） |
| 2 | 账号 B 的真实邮箱 | ❌ 推送被拒：`push declined due to email privacy restrictions` |
| 3 | 账号 B 的 **noreply** 邮箱 | ✅ 关联正确 + 推送通过 |

### 失败原因：GitHub 的邮箱隐私设置

GitHub 账号如果开着：

- **Keep my email addresses private**
- **Block command line pushes that expose my email**

那么用真实邮箱推送会被**直接拒绝**。这是账号所有者自己设的隐私保护，
不是配置错误。

### 解法：用 noreply 邮箱

GitHub 为这个场景专门提供了地址：

```
<账号id>+<用户名>@users.noreply.github.com
```

账号 id 可以从 API 拿到：

```bash
curl -s https://api.github.com/users/<用户名> | grep '"id"'
```

**这个地址同样能关联到你的账号**，而且不暴露真实邮箱——正好符合开隐私设置的意图。

### 改写历史

```bash
git config --local user.email "<noreply邮箱>"

FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --env-filter "export GIT_AUTHOR_EMAIL='<noreply邮箱>'; export GIT_COMMITTER_EMAIL='<noreply邮箱>'" \
  -- --all
```

**改写会改变所有 SHA**，所以两个远端都必须强制推送：

```bash
git push --force-with-lease=master:<远端当前SHA> origin master
git push --force gitee master
```

> **为什么用显式租约**：`git filter-branch` 会把本地的
> `refs/remotes/*/master` 一起重写，导致 `--force-with-lease` 里记录的期望值
> 变成了新 SHA，而远端还是旧 SHA，于是被判定为 "stale info" 而拒绝。
> 显式写出 `<分支>:<期望的远端SHA>` 既绕过这个误触发，又保留了"确认远端没有
> 意外改动"的保护。
>
> 推之前先取远端 SHA 核对：
> ```bash
> git ls-remote origin refs/heads/master
> ```

**别忘了同时改 `user.email`**，否则下一个 commit 又会记错账号。

---

## 三个平台差异（都实际踩到过）

### 1. `ssh -T` 的退出码不一样

| 平台 | 认证成功时的退出码 |
| --- | --- |
| Gitee | `0` |
| GitHub | **`1`**（因为不提供 shell 访问） |

**所以判断认证成功必须解析输出文本**（`successfully authenticated`），
不能看退出码——否则会把 GitHub 的成功读成失败。

```bash
if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "认证成功"
fi
```

### 2. 邮箱隐私拦截（见上一节）

Gitee 没有这个机制。

### 3. 默认分支名

| 平台 | 新建仓库默认分支 |
| --- | --- |
| GitHub | `main` |
| Gitee | `master` |

往一个空仓库推送 `master` 时，GitHub 会把默认分支自动设为实际推上去的那个分支，
所以两边用 `master` 是安全的。

---

## 核对清单

推完之后，**不要只看 git 的输出**，用各平台的 API 独立核对：

```bash
# 两边 SHA 是否一致
git ls-remote origin refs/heads/master
git ls-remote gitee  refs/heads/master

# commit 是否关联到正确的账号（GitHub）
curl -s "https://api.github.com/repos/<user>/<repo>/commits" \
  | grep -E '"(login|email)"'
```

本次核对结果：两个远端 SHA 一致，4/4 个 commit 关联到正确的账号。
