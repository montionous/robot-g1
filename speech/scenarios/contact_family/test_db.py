from db_access import (
    find_family_contact,
    get_elderly,
    list_family_contacts,
)


ELDERLY_ID = 1


elderly = get_elderly(
    ELDERLY_ID
)

print("=" * 60)
print("当前老人")
print("=" * 60)

print(elderly)


print()
print("=" * 60)
print("授权联系人")
print("=" * 60)

for contact in list_family_contacts(
    ELDERLY_ID
):
    print(contact)


tests = [
    "我想和女儿说说话",
    "帮我给闺女打个电话",
    "我想联系儿子",
    "帮我给小李打电话",
]


print()
print("=" * 60)
print("联系人匹配测试")
print("=" * 60)


for text in tests:

    contact = find_family_contact(
        ELDERLY_ID,
        text,
    )

    print()
    print(
        "老人：",
        text
    )

    if contact:

        print(
            "匹配：",
            contact["relation"],
            "/",
            contact["name"],
        )

    else:
        print(
            "匹配失败"
        )
